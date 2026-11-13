/* The reviewer's F1/F2/F3/F6 counterexamples against the O9-S pool library in widgets.c.
   No args: in-process checks (deferred drop, add-while-borrowed, cascade, retire). With an arg: one trap, exit 70. */
#define WIDGETS_AS_LIB
#include "widgets.c"

typedef struct { int v; } Thing;
static int dropped;
static char drop_log[64];
static void thing_drop(void *e) { Thing *t = e; dropped++; size_t n = strlen(drop_log); snprintf(drop_log + n, sizeof drop_log - n, "%d,", t->v); }

#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); exit(1); } } while (0)

int main(int argc, char **argv) {
    Pool things, other;
    pool_init(&things, "things", sizeof(Thing), thing_drop);
    pool_init(&other, "other", sizeof(Thing), thing_drop);
    Thing t = { 7 };
    Handle h = pool_add(&things, &t, NULL_HANDLE);

    if (argc > 1) {                                        /* each of these must trap and exit 70 */
        if (!strcmp(argv[1], "double-borrow")) {           /* (a) F1: two mutable borrows of one entry */
            Thing *a = pool_borrow(&things, h, 1); (void)a;
            Thing *b = pool_borrow(&things, h, 1); (void)b;
        } else if (!strcmp(argv[1], "wrong-pool")) {       /* (d) F6: a handle from pool 'things' used on 'other' */
            pool_add(&other, &t, NULL_HANDLE);
            pool_borrow(&other, h, 0);
        } else if (!strcmp(argv[1], "stale-at")) {         /* F9: pool[h] on a stale handle */
            pool_remove(&things, h);
            pool_at(&things, h);
        } else if (!strcmp(argv[1], "zombie")) {           /* F4: expect_empty finds a forgotten entry */
            pool_expect_empty(&things);
        }
        printf("FAIL: %s did not trap\n", argv[1]);
        return 1;
    }

    /* (b) F2b: remove while borrowed. The handle is stale at once, the drop waits for the release. */
    Thing *e = pool_borrow(&things, h, 0);
    CHECK(pool_remove(&things, h) == 1);
    CHECK(dropped == 0);
    CHECK(pool_borrow(&things, h, 0) == NULL);             /* stale at once */
    CHECK(e->v == 7);                                      /* the borrowed entry is still intact */
    CHECK(pool_remove(&things, h) == 0);                   /* second remove is a no-op */
    pool_release(&things, h);
    CHECK(dropped == 1 && things.live == 0 && things.deferred == 1);
    printf("ok deferred drop: stale at once, dropped at release\n");

    /* (c) F2a: add while borrowed never moves the borrowed entry (1000 adds cross many segments). */
    h = pool_add(&things, &t, NULL_HANDLE);
    Thing *before = pool_borrow(&things, h, 0);
    for (int i = 0; i < 1000; i++) { Thing x = { 100 + i }; pool_add(&things, &x, NULL_HANDLE); }
    Thing *after = pool_borrow(&things, h, 0);             /* a second shared borrow is fine */
    CHECK(before == after && before->v == 7);
    CHECK(things.nseg > 100);
    pool_release(&things, h); pool_release(&things, h);
    printf("ok add while borrowed: pointer unchanged after 1000 adds (%u segments)\n", things.nseg);

    /* F3: owner cascade, nested, with a borrowed grandchild whose drop is deferred. */
    Pool tree; dropped = 0; drop_log[0] = 0;
    pool_init(&tree, "tree", sizeof(Thing), thing_drop);
    Thing r = { 1 }, c1 = { 2 }, c2 = { 3 }, g = { 4 };
    Handle hr = pool_add(&tree, &r, NULL_HANDLE);
    Handle h1 = pool_add(&tree, &c1, hr);
    Handle h2 = pool_add(&tree, &c2, hr);
    Handle hg = pool_add(&tree, &g, h1);
    Thing *gp = pool_borrow(&tree, hg, 1);
    pool_remove(&tree, hr);
    CHECK(!pool_is_live(&tree, h1) && !pool_is_live(&tree, h2) && !pool_is_live(&tree, hg));
    CHECK(strcmp(drop_log, "1,2,3,") == 0 && tree.live == 1);   /* grandchild waits for its release */
    CHECK(gp->v == 4);
    pool_release(&tree, hg);
    CHECK(strcmp(drop_log, "1,2,3,4,") == 0 && tree.live == 0);
    printf("ok owner cascade: dropped %s (grandchild deferred)\n", drop_log);

    /* F6: a slot whose generation would wrap is retired, and its stale handles never match again. */
    Pool r2; pool_init(&r2, "retire", sizeof(Thing), thing_drop);
    Handle a = pool_add(&r2, &t, NULL_HANDLE);
    slot_at(&r2, a.index)->gen = UINT32_MAX - 1; a.gen = UINT32_MAX - 1;
    pool_remove(&r2, a);
    CHECK(r2.retired == 1);
    Handle b = pool_add(&r2, &t, NULL_HANDLE);
    CHECK(b.index != a.index && !pool_is_live(&r2, a));
    printf("ok generation wrap: slot retired, new add used a fresh slot\n");

    pool_free_storage(&things); pool_free_storage(&other); pool_free_storage(&tree); pool_free_storage(&r2);
    printf("all in-process checks passed\n");
    return 0;
}

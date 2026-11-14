/* C model of H1b dispatch (the clarification pass for H1, issue #5). Covers what h1.c did not:
 *  F1  exact values have no vptr: a plain Button on the stack is called directly; only `dyn` carries a vtable;
 *      `self.copy()` and `equals` are virtual (derived per exact class, stored in the vtable).
 *  F3  `take self` and drops. Every class descriptor has a tail_drop function: it drops the own fields of the dynamic
 *      class and its ancestors down to (not including) a given class, SUBCLASS FIRST. A `take self` method ends with
 *      "tail first (everything below me), then my own unmoved fields". `super.close()` receives `self` whole, so a
 *      subclass override that calls it drops nothing itself.
 *  S3  List has six primitives (push, insert, remove_at, get, set, len). Derived methods (push_all, pop, retain) take a
 *      direct path for an exact List and go through the primitive slots for a subclass instance.
 *  S5  an exact receiver runs a copy of the method with direct self-calls.
 * Everything heap-allocated is freed: run under -fsanitize=address (LeakSanitizer) to check. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *dupstr(const char *x) { char *p = (char *)malloc(strlen(x) + 1); strcpy(p, x); return p; }
static char *fmt(const char *f, ...) {
  char buf[256];
  va_list ap;
  va_start(ap, f);
  vsnprintf(buf, sizeof buf, f, ap);
  va_end(ap);
  return dupstr(buf);
}

/* ---------------- class descriptors ---------------- */
typedef struct Class Class;
struct Class {
  const char *name;
  const Class *parent;
  void (*drop_own)(void *);                                              /* the fields this class declares; NULL if none */
  void (*tail_drop)(void *, const Class *dyn, const Class *from);       /* dynamic class .. up to, not including, `from` */
};
static void class_tail_drop(void *o, const Class *dyn, const Class *from) {
  for (const Class *k = dyn; k != NULL && k != from; k = k->parent)      /* most-derived first */
    if (k->drop_own) k->drop_own(o);
}

typedef struct { char *label; } Labelled;                        /* private base fields */
typedef struct { Labelled base; } Button;
typedef struct { Labelled base; int count; char *icon; } Badge;
typedef struct { Labelled base; char *icon; } Tag;

static void Labelled_drop_own(void *o) { printf("  drop Labelled.label\n"); free(((Labelled *)o)->label); }
static void Badge_drop_own(void *o) { printf("  drop Badge.icon\n"); free(((Badge *)o)->icon); }
static void Tag_drop_own(void *o) { printf("  drop Tag.icon\n"); free(((Tag *)o)->icon); }
static const Class Widget_c = { "Widget", NULL, NULL, class_tail_drop };
static const Class Labelled_c = { "Labelled", &Widget_c, Labelled_drop_own, class_tail_drop };
static const Class Button_c = { "Button", &Labelled_c, NULL, class_tail_drop };
static const Class Badge_c = { "Badge", &Labelled_c, Badge_drop_own, class_tail_drop };
static const Class Tag_c = { "Tag", &Labelled_c, Tag_drop_own, class_tail_drop };

/* ---------------- dyn Labelled ---------------- */
typedef struct LVT LVT;
typedef struct { void *p; const LVT *vt; } Dyn;
struct LVT {
  const Class *cls;                                                         /* first member of every vtable */
  const char *(*kind)(void *, const LVT *);
  char *(*text)(void *, const LVT *);
  char *(*render)(void *, const LVT *, int depth);
  char *(*close)(void *, const LVT *);                                     /* take self: consumes the value's fields */
  char *(*into_label)(void *, const LVT *);                                /* take self: moves label out */
  Dyn (*copy)(const void *, const LVT *);                                  /* derived per exact class */
  int (*equals)(const void *, const void *, const LVT *);                  /* derived per exact class; classes must match */
};
static Dyn box(const void *obj, size_t n, const LVT *vt) { void *p = malloc(n); memcpy(p, obj, n); Dyn d = { p, vt }; return d; }

static char *Labelled_text(void *s, const LVT *vt) { (void)vt; return dupstr(((Labelled *)s)->label); }
static char *Labelled_render(void *s, const LVT *vt, int depth) {          /* template method: open self-calls */
  const char *k = vt->kind(s, vt);
  char *t = vt->text(s, vt);
  char *out = fmt("%*s%s %s", depth * 2, "", k, t);
  free(t);
  return out;
}
static char *Labelled_close(void *s, const LVT *vt) {                      /* take self */
  const char *k = vt->kind(s, vt);
  char *t = vt->text(s, vt);
  char *out = fmt("%s %s", k, t);
  free(t);
  vt->cls->tail_drop(s, vt->cls, &Labelled_c);                             /* the tail: subclass fields first */
  Labelled_drop_own(s);                                                    /* then my own unmoved fields */
  return out;
}
static char *Labelled_into_label(void *s, const LVT *vt) {                 /* take self; moves `label` out */
  char *lab = ((Labelled *)s)->label;                                      /* moved: Labelled's own drop is skipped */
  vt->cls->tail_drop(s, vt->cls, &Labelled_c);                             /* the tail still drops */
  return lab;
}
static const char *Button_kind(void *s, const LVT *vt) { (void)s; (void)vt; return "Button"; }
static const char *Badge_kind(void *s, const LVT *vt) { (void)s; (void)vt; return "Badge"; }
static const char *Tag_kind(void *s, const LVT *vt) { (void)s; (void)vt; return "Tag"; }
static char *Badge_text(void *s, const LVT *vt) { (void)vt; Badge *b = (Badge *)s; return fmt("%s x%d %s", b->base.label, b->count, b->icon); }
static char *Badge_close(void *s, const LVT *vt) {
  printf("  closing badge %d\n", ((Badge *)s)->count);
  return Labelled_close(s, vt);                                            /* super.close(): self whole, nothing after */
}
/* derived per exact class (generated code, one copy and one equals per class) */
static const LVT Button_vt, Badge_vt, Tag_vt;
static Dyn Button_copy(const void *s, const LVT *vt) { Button b = { { dupstr(((const Labelled *)s)->label) } }; return box(&b, sizeof b, vt); }
static Dyn Badge_copy(const void *s, const LVT *vt) {
  const Badge *o = (const Badge *)s;
  Badge b = { { dupstr(o->base.label) }, o->count, dupstr(o->icon) };
  return box(&b, sizeof b, vt);
}
static Dyn Tag_copy(const void *s, const LVT *vt) {
  const Tag *o = (const Tag *)s;
  Tag b = { { dupstr(o->base.label) }, dupstr(o->icon) };
  return box(&b, sizeof b, vt);
}
static int Button_equals(const void *a, const void *b, const LVT *vt) { (void)vt; return strcmp(((const Labelled *)a)->label, ((const Labelled *)b)->label) == 0; }
static int Badge_equals(const void *a, const void *b, const LVT *vt) {
  (void)vt;
  const Badge *x = (const Badge *)a, *y = (const Badge *)b;
  return strcmp(x->base.label, y->base.label) == 0 && x->count == y->count && strcmp(x->icon, y->icon) == 0;
}
static int Tag_equals(const void *a, const void *b, const LVT *vt) {
  (void)vt;
  const Tag *x = (const Tag *)a, *y = (const Tag *)b;
  return strcmp(x->base.label, y->base.label) == 0 && strcmp(x->icon, y->icon) == 0;
}
static const LVT Button_vt = { &Button_c, Button_kind, Labelled_text, Labelled_render, Labelled_close, Labelled_into_label, Button_copy, Button_equals };
static const LVT Badge_vt = { &Badge_c, Badge_kind, Badge_text, Labelled_render, Badge_close, Labelled_into_label, Badge_copy, Badge_equals };
static const LVT Tag_vt = { &Tag_c, Tag_kind, Labelled_text, Labelled_render, Labelled_close, Labelled_into_label, Tag_copy, Tag_equals };

static Dyn mk_button(const char *l) { Button b = { { dupstr(l) } }; return box(&b, sizeof b, &Button_vt); }
static Dyn mk_badge(const char *l, int n, const char *i) { Badge b = { { dupstr(l) }, n, dupstr(i) }; return box(&b, sizeof b, &Badge_vt); }
static Dyn mk_tag(const char *l, const char *i) { Tag b = { { dupstr(l) }, dupstr(i) }; return box(&b, sizeof b, &Tag_vt); }
static void dyn_drop(Dyn d) { d.vt->cls->tail_drop(d.p, d.vt->cls, NULL); free(d.p); }   /* plain drop: whole chain, subclass first */
static char *dyn_close(Dyn d) { char *r = d.vt->close(d.p, d.vt); free(d.p); return r; }   /* take self: storage freed by the owner */
static int dyn_equals(Dyn a, Dyn b) { return a.vt->cls == b.vt->cls && a.vt->equals(a.p, b.p, a.vt); }
static void say(const char *tag, char *owned) { printf("%s%s\n", tag, owned); free(owned); }

/* S5: the compiler instantiates Labelled.render for the exact class Button: every self-call is a direct call, no vtable. */
static char *Labelled_render__Button(Button *b, int depth) {
  const char *k = Button_kind(b, NULL);
  char *t = Labelled_text(b, NULL);
  char *out = fmt("%*s%s %s", depth * 2, "", k, t);
  free(t);
  return out;
}

/* ---------------- List: six primitives, derived methods ---------------- */
typedef struct ListVT ListVT;
typedef struct { char *items[16]; int n; } List;
struct ListVT {
  const char *cls;
  void (*push)(void *, const ListVT *, const char *);
  void (*insert)(void *, const ListVT *, int, const char *);
  char *(*remove_at)(void *, const ListVT *, int);
  const char *(*get)(void *, const ListVT *, int);
  void (*set)(void *, const ListVT *, int, const char *);
  int (*len)(void *, const ListVT *);
  void (*push_all)(void *, const ListVT *, const char **, int);           /* derived */
  char *(*pop)(void *, const ListVT *);                                    /* derived */
  void (*retain)(void *, const ListVT *, int (*keep)(const char *));      /* derived */
};
static int slot_calls = 0;                                                 /* primitive SLOT calls (not raw storage access) */
static void raw_insert(List *l, int at, const char *x) {
  for (int i = l->n; i > at; i--) l->items[i] = l->items[i - 1];
  l->items[at] = dupstr(x);
  l->n++;
}
static char *raw_remove(List *l, int at) {
  char *x = l->items[at];
  for (int i = at; i < l->n - 1; i++) l->items[i] = l->items[i + 1];
  l->n--;
  return x;
}
static void List_push(void *s, const ListVT *vt, const char *x) { (void)vt; slot_calls++; raw_insert((List *)s, ((List *)s)->n, x); }
static void List_insert(void *s, const ListVT *vt, int at, const char *x) { (void)vt; slot_calls++; raw_insert((List *)s, at, x); }
static char *List_remove_at(void *s, const ListVT *vt, int at) { (void)vt; slot_calls++; return raw_remove((List *)s, at); }
static const char *List_get(void *s, const ListVT *vt, int at) { (void)vt; slot_calls++; return ((List *)s)->items[at]; }
static void List_set(void *s, const ListVT *vt, int at, const char *x) { (void)vt; slot_calls++; free(((List *)s)->items[at]); ((List *)s)->items[at] = dupstr(x); }
static int List_len(void *s, const ListVT *vt) { (void)vt; slot_calls++; return ((List *)s)->n; }
static const ListVT List_vt;
static void List_push_all(void *s, const ListVT *vt, const char **xs, int n) {
  if (vt == &List_vt) { for (int i = 0; i < n; i++) raw_insert((List *)s, ((List *)s)->n, xs[i]); return; }   /* exact List: direct */
  for (int i = 0; i < n; i++) vt->push(s, vt, xs[i]);                                                       /* subclass: via push */
}
static char *List_pop(void *s, const ListVT *vt) {
  List *l = (List *)s;
  if (vt == &List_vt) return l->n ? raw_remove(l, l->n - 1) : NULL;
  int n = vt->len(s, vt);
  return n ? vt->remove_at(s, vt, n - 1) : NULL;
}
static void List_retain(void *s, const ListVT *vt, int (*keep)(const char *)) {
  List *l = (List *)s;
  if (vt == &List_vt) { for (int i = l->n - 1; i >= 0; i--) if (!keep(l->items[i])) free(raw_remove(l, i)); return; }
  for (int i = vt->len(s, vt) - 1; i >= 0; i--) if (!keep(vt->get(s, vt, i))) free(vt->remove_at(s, vt, i));
}
static const ListVT List_vt = { "List", List_push, List_insert, List_remove_at, List_get, List_set, List_len, List_push_all, List_pop, List_retain };

typedef struct { List l; } LoggedNames;
typedef struct { List l; int n; } CountedNames;
typedef struct { List l; } SortedNames;
static void LoggedNames_push(void *s, const ListVT *vt, const char *x) { printf("  log push %s\n", x); List_push(s, vt, x); }
static void CountedNames_push(void *s, const ListVT *vt, const char *x) { ((CountedNames *)s)->n += 1; LoggedNames_push(s, vt, x); }
static void SortedNames_insert(void *s, const ListVT *vt, int at, const char *x) {
  int i = 0;
  (void)at;                                                                /* the position is ours to choose */
  while (i < vt->len(s, vt) && strcmp(vt->get(s, vt, i), x) < 0) i++;
  List_insert(s, vt, i, x);                                                /* super.insert */
}
static void SortedNames_push(void *s, const ListVT *vt, const char *x) { vt->insert(s, vt, vt->len(s, vt), x); }
static const ListVT LoggedNames_vt = { "LoggedNames", LoggedNames_push, List_insert, List_remove_at, List_get, List_set, List_len, List_push_all, List_pop, List_retain };
static const ListVT CountedNames_vt = { "CountedNames", CountedNames_push, List_insert, List_remove_at, List_get, List_set, List_len, List_push_all, List_pop, List_retain };
static const ListVT SortedNames_vt = { "SortedNames", SortedNames_push, SortedNames_insert, List_remove_at, List_get, List_set, List_len, List_push_all, List_pop, List_retain };

static void list_free(List *l) { for (int i = 0; i < l->n; i++) free(l->items[i]); l->n = 0; }
static void show_list(const char *tag, List *l) {
  printf("%s = [", tag);
  for (int i = 0; i < l->n; i++) printf("%s%s", i ? " " : "", l->items[i]);
  printf("]\n");
}
static int is_sorted(List *l) { for (int i = 1; i < l->n; i++) if (strcmp(l->items[i - 1], l->items[i]) > 0) return 0; return 1; }
static int not_fig(const char *x) { return strcmp(x, "fig") != 0; }
static void fill(void *p, const ListVT *vt, const char **more, int n) { vt->push_all(p, vt, more, n); }   /* names: dyn List of Str */

int main(void) {
  printf("== F3 take self and drops (dyn Labelled; a tail-drop per class descriptor) ==\n");
  Dyn bd = mk_badge("inbox", 3, "mail"), tg = mk_tag("beta", "star"), bt = mk_button("OK");
  say("render: ", bd.vt->render(bd.p, bd.vt, 0));
  say("render: ", tg.vt->render(tg.p, tg.vt, 0));
  say("render: ", bt.vt->render(bt.p, bt.vt, 0));
  printf("close Badge (override calls super.close()):\n");
  say("closed: ", dyn_close(bd));
  printf("close Tag (inherited close):\n");
  say("closed: ", dyn_close(tg));
  printf("close Button:\n");
  say("closed: ", dyn_close(bt));
  printf("into_label on a Badge (moves label out; the tail still drops):\n");
  Dyn nb = mk_badge("note", 1, "pin");
  char *lab = nb.vt->into_label(nb.p, nb.vt);
  free(nb.p);
  say("moved label = ", lab);
  printf("plain drop of a Tag (subclass fields first):\n");
  dyn_drop(mk_tag("temp", "bolt"));

  printf("== F1 virtual copy and per-class equals ==\n");
  Dyn a = mk_badge("inbox", 3, "mail");
  Dyn c = a.vt->copy(a.p, a.vt);                                          /* self.copy() inside a method: virtual */
  printf("copy of a Badge is a %s, equals original: %s\n", c.vt->cls->name, dyn_equals(a, c) ? "yes" : "no");
  Dyn k1 = mk_button("OK"), k2 = mk_tag("OK", "x");
  printf("Button OK equals Tag OK: %s (same label, different exact class)\n", dyn_equals(k1, k2) ? "yes" : "no");
  dyn_drop(a); dyn_drop(c); dyn_drop(k1); dyn_drop(k2);

  printf("== S5 exact receiver: direct calls, no vtable ==\n");
  Button eb = { { dupstr("Exact") } };
  char *viaexact = Labelled_render__Button(&eb, 1);
  Dyn eb_d = box(&eb, sizeof eb, &Button_vt);                             /* the same value as a dyn */
  char *viadyn = eb_d.vt->render(eb_d.p, eb_d.vt, 1);
  printf("exact: [%s]  dyn: [%s]  same: %s\n", viaexact, viadyn, strcmp(viaexact, viadyn) == 0 ? "yes" : "no");
  free(viaexact); free(viadyn);
  dyn_drop(eb_d);

  printf("== S3 LoggedNames: push_all goes through the push primitive ==\n");
  LoggedNames ln = { { { 0 }, 0 } };
  const char *bc[] = { "b", "c" }, *w[] = { "w" }, *xy[] = { "x", "y" };
  printf("a.push(a)\n");
  LoggedNames_push(&ln, &LoggedNames_vt, "a");
  printf("a.push_all([b, c])\n");
  LoggedNames_vt.push_all(&ln, &LoggedNames_vt, bc, 2);
  show_list("a", &ln.l);
  CountedNames cn = { { { 0 }, 0 }, 0 };
  printf("c.push_all([x, y])   (CountedNames overrides push only)\n");
  CountedNames_vt.push_all(&cn, &CountedNames_vt, xy, 2);
  printf("c.n = %d\n", cn.n);
  printf("fill(dyn List c, [w])\n");
  fill(&cn, &CountedNames_vt, w, 1);
  printf("c.n = %d\n", cn.n);
  show_list("c", &cn.l);
  printf("exact List p.push_all([p, q]):\n");
  List pl = { { 0 }, 0 };
  const char *pq[] = { "p", "q" };
  int before = slot_calls;
  List_vt.push_all(&pl, &List_vt, pq, 2);
  printf("primitive slot calls = %d (direct path)\n", slot_calls - before);
  show_list("p", &pl);
  LoggedNames tmp = { { { 0 }, 0 } };
  printf("LoggedNames t.push_all([p, q]):\n");
  before = slot_calls;
  LoggedNames_vt.push_all(&tmp, &LoggedNames_vt, pq, 2);
  printf("primitive slot calls = %d (through push)\n", slot_calls - before);

  printf("== S3 SortedNames: push and insert keep the order through every derived method ==\n");
  SortedNames sn = { { { 0 }, 0 } };
  const char *fruit[] = { "pear", "apple", "fig" };
  SortedNames_vt.push_all(&sn, &SortedNames_vt, fruit, 3);
  show_list("s after push_all([pear, apple, fig])", &sn.l);
  SortedNames_vt.insert(&sn, &SortedNames_vt, 0, "zebra");
  show_list("s after insert(at: 0, zebra)", &sn.l);
  SortedNames_vt.retain(&sn, &SortedNames_vt, not_fig);
  show_list("s after retain(not fig)", &sn.l);
  char *top = SortedNames_vt.pop(&sn, &SortedNames_vt);
  printf("s.pop() = %s\n", top);
  free(top);
  show_list("s", &sn.l);
  printf("sorted: %s\n", is_sorted(&sn.l) ? "yes" : "no");

  list_free(&ln.l); list_free(&cn.l); list_free(&pl); list_free(&tmp.l); list_free(&sn.l);
  return 0;
}

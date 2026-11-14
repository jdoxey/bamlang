/* C model of H2 dispatch (ADR-0005 amendment 1): one parent with fields plus field-less parents; closed recursion.
 *
 *  - Objects have no vptr. The one stateful parent chain fixes the object layout (Button's fields come first); a
 *    stateless parent (Saveable) adds no fields, so converting an object pointer to its Saveable view needs no
 *    pointer adjustment: only a different VTABLE.
 *  - Every class has a descriptor `Desc` with one view vtable per parent role it fills (widget, saveable, shape, list).
 *    `dyn Widget` and `dyn Saveable` are the same object pointer plus different views (the second-parent vtable).
 *  - Every method receives the dynamic descriptor `dc` (hidden parameter). A hook or abstract self-call is
 *    `dc->view->m(...)`; every other self-call is a direct call. `super(Parent).m()` is a direct call.
 *  - A method inherited from both parents (describe) has no slot ambiguity because the class must override it.
 *  - The built-in List never calls its own overridable methods. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Desc Desc;
typedef struct { void *p; const void *vt; } Dyn;           /* dyn Base: pointer + the view vtable of the dynamic class */
static Dyn box(const void *obj, size_t n, const void *vt) {
  void *p = malloc(n);
  memcpy(p, obj, n);
  Dyn d = { p, vt };
  return d;
}
#define PI 3.14159265358979
#define SQRT3 1.7320508075688772

typedef struct { const Desc *dc; double (*area)(void *, const Desc *); const char *(*name)(void *, const Desc *);
                 void (*describe)(void *, const Desc *); } ShapeVT;
typedef struct { const Desc *dc;
                 void (*render)(void *, const Desc *, int);
                 void (*click)(void *, const Desc *);
                 const char *(*focus_next)(void *, const Desc *);
                 void (*describe)(void *, const Desc *, char *, size_t);
                 const char *(*kind)(void *, const Desc *);      /* Labelled's steps; NULL for other widgets */
                 const char *(*text)(void *, const Desc *); } WidgetVT;
typedef struct { const Desc *dc; const char *(*save)(void *, const Desc *);
                 void (*describe)(void *, const Desc *, char *, size_t); } SaveableVT;
typedef struct { const Desc *dc; void (*push)(void *, const Desc *, const char *);
                 void (*push_all)(void *, const Desc *, const char **, int); } ListVT;
struct Desc { const char *name; const ShapeVT *shape; const WidgetVT *widget; const SaveableVT *saveable; const ListVT *list; };

/* ============ B1 Shape ============ */
typedef struct { double r; } Circle;
typedef struct { double w, h; } Rect;
typedef struct { double side; } Hexagon;
static double Circle_area(void *s, const Desc *dc) { (void)dc; Circle *c = s; return PI * c->r * c->r; }
static const char *Circle_name(void *s, const Desc *dc) { (void)s; (void)dc; return "circle"; }
static double Rect_area(void *s, const Desc *dc) { (void)dc; Rect *c = s; return c->w * c->h; }
static const char *Rect_name(void *s, const Desc *dc) { (void)s; (void)dc; return "rect"; }
static double Hexagon_area(void *s, const Desc *dc) { (void)dc; Hexagon *c = s; return 3.0 * SQRT3 / 2.0 * c->side * c->side; }
static const char *Hexagon_name(void *s, const Desc *dc) { (void)s; (void)dc; return "hexagon"; }
static void Shape_describe(void *s, const Desc *dc) {          /* name, area are abstract: through the view */
  const char *n = dc->shape->name(s, dc);
  printf("%s %.2f\n", n, dc->shape->area(s, dc));
}
static ShapeVT Circle_shape, Rect_shape, Hexagon_shape;
static const Desc Circle_desc = { "Circle", &Circle_shape, 0, 0, 0 };
static const Desc Rect_desc = { "Rect", &Rect_shape, 0, 0, 0 };
static const Desc Hexagon_desc = { "Hexagon", &Hexagon_shape, 0, 0, 0 };
static ShapeVT Circle_shape = { &Circle_desc, Circle_area, Circle_name, Shape_describe };
static ShapeVT Rect_shape = { &Rect_desc, Rect_area, Rect_name, Shape_describe };
static ShapeVT Hexagon_shape = { &Hexagon_desc, Hexagon_area, Hexagon_name, Shape_describe };

/* ============ B2 widgets ============ */
typedef struct { char label[32]; } Labelled;
typedef struct { Labelled l; } Button;
typedef struct { Labelled l; int count; } Badge;
typedef struct { Button b; } SaveableButton;     /* Button's fields; Saveable adds none */
typedef struct { int value, max; } Slider;

static const char *Widget_focus_next(void *s, const Desc *dc) { (void)s; (void)dc; return "focus moves to next"; }
static void Widget_describe(void *s, const Desc *dc, char *out, size_t n) { (void)s; (void)dc; snprintf(out, n, "widget"); }
static const char *Labelled_text(void *s, const Desc *dc) { (void)dc; return ((Labelled *)s)->label; }
static void Labelled_render(void *s, const Desc *dc, int depth) {
  const char *k = dc->widget->kind(s, dc);                            /* abstract: through the view */
  printf("%*s%s %s\n", depth * 2, "", k, dc->widget->text(s, dc));    /* hook fn text: through the view */
}
static const char *Button_kind(void *s, const Desc *dc) { (void)s; (void)dc; return "Button"; }
static void Button_click(void *s, const Desc *dc) {
  printf("pressed %s; %s\n", ((Labelled *)s)->label, Widget_focus_next(s, dc));   /* closed: direct */
}
static const char *Badge_kind(void *s, const Desc *dc) { (void)s; (void)dc; return "Badge"; }
static const char *Badge_text(void *s, const Desc *dc) {
  static char buf[64];
  (void)dc;
  snprintf(buf, sizeof buf, "%s x%d", ((Labelled *)s)->label, ((Badge *)s)->count);
  return buf;
}
static void Badge_click(void *s, const Desc *dc) { (void)s; (void)dc; printf("ignored\n"); }
static void Slider_render(void *s, const Desc *dc, int depth) {
  Slider *l = s;
  (void)dc;
  printf("%*sSlider %d/%d\n", depth * 2, "", l->value, l->max);
}
static void Slider_click(void *s, const Desc *dc) { (void)s; (void)dc; printf("ignored\n"); }
static const char *QuietButton_focus_next(void *s, const Desc *dc) { (void)s; (void)dc; return "focus stays"; }

/* ============ (a) two roles: SaveableButton is Button, Saveable ============ */
static void Saveable_describe(void *s, const Desc *dc, char *out, size_t n) {
  snprintf(out, n, "saveable %s", dc->saveable->save(s, dc));      /* abstract save: through the Saveable view */
}
static const char *SaveableButton_save(void *s, const Desc *dc) {
  static char buf[64];
  (void)dc;
  snprintf(buf, sizeof buf, "button:%s", ((Labelled *)s)->label);
  return buf;
}
static void SaveableButton_describe(void *s, const Desc *dc, char *out, size_t n) {
  char a[64], b[64];
  Saveable_describe(s, dc, a, sizeof a);       /* super(Saveable).describe(): direct */
  Widget_describe(s, dc, b, sizeof b);         /* super(Button).describe(): direct, found 3 classes up */
  snprintf(out, n, "%s / %s", a, b);
}

static WidgetVT Button_w, QuietButton_w, Badge_w, Slider_w, SaveableButton_w;
static SaveableVT SaveableButton_s;
static const Desc Button_desc = { "Button", 0, &Button_w, 0, 0 };
static const Desc QuietButton_desc = { "QuietButton", 0, &QuietButton_w, 0, 0 };
static const Desc Badge_desc = { "Badge", 0, &Badge_w, 0, 0 };
static const Desc Slider_desc = { "Slider", 0, &Slider_w, 0, 0 };
static const Desc SaveableButton_desc = { "SaveableButton", 0, &SaveableButton_w, &SaveableButton_s, 0 };
static WidgetVT Button_w = { &Button_desc, Labelled_render, Button_click, Widget_focus_next, Widget_describe, Button_kind, Labelled_text };
static WidgetVT QuietButton_w = { &QuietButton_desc, Labelled_render, Button_click, QuietButton_focus_next, Widget_describe, Button_kind, Labelled_text };
static WidgetVT Badge_w = { &Badge_desc, Labelled_render, Badge_click, Widget_focus_next, Widget_describe, Badge_kind, Badge_text };
static WidgetVT Slider_w = { &Slider_desc, Slider_render, Slider_click, Widget_focus_next, Widget_describe, 0, 0 };
static WidgetVT SaveableButton_w = { &SaveableButton_desc, Labelled_render, Button_click, Widget_focus_next, SaveableButton_describe, Button_kind, Labelled_text };
static SaveableVT SaveableButton_s = { &SaveableButton_desc, SaveableButton_save, SaveableButton_describe };

/* ============ (b) subclassing the built-in List ============ */
typedef struct { char *items[16]; int n; } List;
static char *dupstr(const char *x) { char *p = malloc(strlen(x) + 1); strcpy(p, x); return p; }
static void list_append(List *l, const char *x) { l->items[l->n++] = dupstr(x); }
static void List_push(void *s, const Desc *dc, const char *x) { (void)dc; list_append(s, x); }
static void List_push_all(void *s, const Desc *dc, const char **xs, int n) {
  (void)dc;
  for (int i = 0; i < n; i++) list_append(s, xs[i]);     /* built-ins never call their own overridable push */
}
typedef struct { List l; } LoggedNames;
typedef struct { List l; } LoggedAll;
typedef struct { List l; int n; } CountedNames;
static void LoggedNames_push(void *s, const Desc *dc, const char *x) {
  printf("  log push %s\n", x);
  List_push(s, dc, x);                                    /* super.push(x): direct */
}
static void LoggedAll_push_all(void *s, const Desc *dc, const char **xs, int n) {
  for (int i = 0; i < n; i++) LoggedNames_push(s, dc, xs[i]);   /* self.push(x): closed, direct to LoggedNames.push */
}
static void CountedNames_push(void *s, const Desc *dc, const char *x) {
  ((CountedNames *)s)->n += 1;
  LoggedNames_push(s, dc, x);                             /* super.push(x): direct */
}
static ListVT List_l, LoggedNames_l, LoggedAll_l, CountedNames_l;
static const Desc List_desc = { "List", 0, 0, 0, &List_l };
static const Desc LoggedNames_desc = { "LoggedNames", 0, 0, 0, &LoggedNames_l };
static const Desc LoggedAll_desc = { "LoggedAll", 0, 0, 0, &LoggedAll_l };
static const Desc CountedNames_desc = { "CountedNames", 0, 0, 0, &CountedNames_l };
static ListVT List_l = { &List_desc, List_push, List_push_all };
static ListVT LoggedNames_l = { &LoggedNames_desc, LoggedNames_push, List_push_all };
static ListVT LoggedAll_l = { &LoggedAll_desc, LoggedNames_push, LoggedAll_push_all };
static ListVT CountedNames_l = { &CountedNames_desc, CountedNames_push, LoggedAll_push_all };
static void fill(Dyn names, const char **more, int n) {
  const ListVT *vt = names.vt;
  vt->push_all(names.p, vt->dc, more, n);
}
static void show_list(const char *tag, List *l) {
  printf("%s = [", tag);
  for (int i = 0; i < l->n; i++) printf("%s%s", i ? " " : "", l->items[i]);
  printf("]\n");
}

int main(void) {
  printf("== H2 shapes (dyn Shape: describe -> abstract name, area through the view) ==\n");
  Circle c = { 1.0 };
  Hexagon h = { 2.0 };
  Rect r = { 2.0, 3.0 };
  Dyn shapes[3] = { box(&c, sizeof c, &Circle_shape), box(&h, sizeof h, &Hexagon_shape), box(&r, sizeof r, &Rect_shape) };
  for (int i = 0; i < 3; i++) { const ShapeVT *vt = shapes[i].vt; vt->describe(shapes[i].p, vt->dc); }
  printf("plain Circle area (direct call, no vtable): %.2f\n", Circle_area(&c, &Circle_desc));

  printf("== H2 widgets (template method; kind/text through the view, focus_next direct) ==\n");
  Button ok = { { "OK" } };
  Button q = { { "Q" } };
  Badge bd = { { "inbox" }, 3 };
  Slider sl = { 3, 10 };
  Dyn ws[4] = { box(&ok, sizeof ok, &Button_w), box(&sl, sizeof sl, &Slider_w), box(&bd, sizeof bd, &Badge_w), box(&q, sizeof q, &QuietButton_w) };
  for (int i = 0; i < 4; i++) { const WidgetVT *vt = ws[i].vt; printf("render "); vt->render(ws[i].p, vt->dc, 0); }
  { const WidgetVT *vt = ws[0].vt; printf("click OK: "); vt->click(ws[0].p, vt->dc); }
  { const WidgetVT *vt = ws[3].vt; printf("click QuietButton Q: "); vt->click(ws[3].p, vt->dc); }

  printf("== H2 two roles (SaveableButton is Button, Saveable: one object, two views) ==\n");
  SaveableButton sb = { { { "Save" } } };
  Dyn sw = { &sb, &SaveableButton_w };                       /* dyn Widget: Widget view of the same object */
  Dyn sv = { &sb, &SaveableButton_s };                       /* dyn Saveable: Saveable view, same pointer */
  char buf[96];
  { const WidgetVT *vt = sw.vt; printf("as widget: "); vt->render(sw.p, vt->dc, 0); vt->describe(sw.p, vt->dc, buf, sizeof buf); printf("describe via Widget view: %s\n", buf); }
  { const SaveableVT *vt = sv.vt; printf("as saveable: %s\n", vt->save(sv.p, vt->dc)); vt->describe(sv.p, vt->dc, buf, sizeof buf); printf("describe via Saveable view: %s\n", buf); }
  printf("same object: %s\n", sw.p == sv.p ? "yes" : "no");

  printf("== H2 LoggedNames (subclass of the built-in List) ==\n");
  LoggedNames a = { { { 0 }, 0 } };
  const char *bc[] = { "b", "c" }, *xy[] = { "x", "y" }, *w[] = { "w" };
  printf("a.push(a)\n");
  LoggedNames_push(&a, &LoggedNames_desc, "a");
  printf("a.push_all([b, c])\n");
  LoggedNames_l.push_all(&a, &LoggedNames_desc, bc, 2);          /* resolves to List.push_all: no log lines */
  show_list("a", &a.l);
  CountedNames cn = { { { 0 }, 0 }, 0 };
  printf("c.push_all([x, y])\n");
  CountedNames_l.push_all(&cn, &CountedNames_desc, xy, 2);
  printf("c.n = %d\n", cn.n);
  printf("c.push(z)\n");
  CountedNames_push(&cn, &CountedNames_desc, "z");
  printf("c.n = %d\n", cn.n);
  printf("plain List p.push_all([p, q]) (exactly List)\n");
  List pl = { { 0 }, 0 };
  const char *pq[] = { "p", "q" };
  List_l.push_all(&pl, &List_desc, pq, 2);
  show_list("p", &pl);
  printf("LoggedAll d.push_all([m])\n");
  LoggedAll d = { { { 0 }, 0 } };
  const char *mm[] = { "m" };
  LoggedAll_l.push_all(&d, &LoggedAll_desc, mm, 1);
  printf("fill(dyn List c, [w])\n");
  Dyn cd = { &cn, &CountedNames_l };
  fill(cd, w, 1);
  printf("c.n = %d\n", cn.n);
  show_list("c", &cn.l);
  return 0;
}

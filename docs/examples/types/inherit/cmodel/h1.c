/* C model of H1 dispatch (ADR-0005 amendment 1): single inheritance, open recursion, built-ins never self-call.
 *
 *  - An object has NO vptr: a plain `Circle` value is exactly a Circle, so calls on it are direct (slicing is impossible).
 *  - A vtable per class lists every slot of its ancestors first (inherited slots point at the ancestor's function),
 *    then its own new slots. A subclass vtable starts with the parent's vtable, so a vtable pointer converts upward.
 *  - `dyn Base` is a boxed pointer + the dynamic class's vtable.
 *  - Open recursion: every method receives the DYNAMIC class's vtable (hidden parameter `vt`) and a self-call
 *    `self.m()` is `vt->m(...)`. That hidden parameter is the price H1 pays on every method.
 *  - `super.m()` is a direct call. The built-in List never calls its own overridable methods. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { void *p; const void *vt; } Dyn;           /* dyn Base: pointer + vtable */
static Dyn box(const void *obj, size_t n, const void *vt) { /* a store site: copies the value to the heap */
  void *p = malloc(n);
  memcpy(p, obj, n);
  Dyn d = { p, vt };
  return d;
}
#define PI 3.14159265358979
#define SQRT3 1.7320508075688772

/* ============ B1 Shape: abstract area/name, provided describe (open self-calls) ============ */
typedef struct ShapeVT ShapeVT;
struct ShapeVT {
  const char *cls;
  double (*area)(void *, const ShapeVT *);
  const char *(*name)(void *, const ShapeVT *);
  void (*describe)(void *, const ShapeVT *);
};
typedef struct { double r; } Circle;
typedef struct { double w, h; } Rect;
typedef struct { double side; } Hexagon;
static double Circle_area(void *s, const ShapeVT *vt) { (void)vt; Circle *c = s; return PI * c->r * c->r; }
static const char *Circle_name(void *s, const ShapeVT *vt) { (void)s; (void)vt; return "circle"; }
static double Rect_area(void *s, const ShapeVT *vt) { (void)vt; Rect *c = s; return c->w * c->h; }
static const char *Rect_name(void *s, const ShapeVT *vt) { (void)s; (void)vt; return "rect"; }
static double Hexagon_area(void *s, const ShapeVT *vt) { (void)vt; Hexagon *c = s; return 3.0 * SQRT3 / 2.0 * c->side * c->side; }
static const char *Hexagon_name(void *s, const ShapeVT *vt) { (void)s; (void)vt; return "hexagon"; }
static void Shape_describe(void *s, const ShapeVT *vt) {      /* self.name(), self.area(): both through vt */
  const char *n = vt->name(s, vt);
  printf("%s %.2f\n", n, vt->area(s, vt));
}
static const ShapeVT Circle_vt = { "Circle", Circle_area, Circle_name, Shape_describe };
static const ShapeVT Rect_vt = { "Rect", Rect_area, Rect_name, Shape_describe };
static const ShapeVT Hexagon_vt = { "Hexagon", Hexagon_area, Hexagon_name, Shape_describe };

/* ============ B2 Widget / Labelled / Button / Badge / Slider ============ */
typedef struct WidgetVT WidgetVT;
struct WidgetVT {
  const char *cls;
  void (*render)(void *, const WidgetVT *, int depth);
  void (*click)(void *, const WidgetVT *);
  const char *(*focus_next)(void *, const WidgetVT *);
};
typedef struct { WidgetVT w; const char *(*kind)(void *, const WidgetVT *); const char *(*text)(void *, const WidgetVT *); } LabelledVT;
typedef struct { char label[32]; } Labelled;       /* fields of Labelled */
typedef struct { Labelled l; } Button;
typedef struct { Labelled l; int count; } Badge;
typedef struct { int value, max; } Slider;

static const char *Widget_focus_next(void *s, const WidgetVT *vt) { (void)s; (void)vt; return "focus moves to next"; }
static const char *Labelled_text(void *s, const WidgetVT *vt) { (void)vt; return ((Labelled *)s)->label; }
static void Labelled_render(void *s, const WidgetVT *vt, int depth) {   /* template method */
  const LabelledVT *lv = (const LabelledVT *)vt;
  const char *k = lv->kind(s, vt);                   /* open self-call */
  printf("%*s%s %s\n", depth * 2, "", k, lv->text(s, vt));   /* open self-call */
}
static const char *Button_kind(void *s, const WidgetVT *vt) { (void)s; (void)vt; return "Button"; }
static void Button_click(void *s, const WidgetVT *vt) {
  printf("pressed %s; %s\n", ((Labelled *)s)->label, vt->focus_next(s, vt));   /* self.focus_next(): open, through vt */
}
static const char *Badge_kind(void *s, const WidgetVT *vt) { (void)s; (void)vt; return "Badge"; }
static const char *Badge_text(void *s, const WidgetVT *vt) {
  static char buf[64];
  (void)vt;
  snprintf(buf, sizeof buf, "%s x%d", ((Labelled *)s)->label, ((Badge *)s)->count);
  return buf;
}
static void Badge_click(void *s, const WidgetVT *vt) { (void)s; (void)vt; printf("ignored\n"); }
static void Slider_render(void *s, const WidgetVT *vt, int depth) {
  Slider *l = s;
  (void)vt;
  printf("%*sSlider %d/%d\n", depth * 2, "", l->value, l->max);
}
static void Slider_click(void *s, const WidgetVT *vt) { (void)s; (void)vt; printf("ignored\n"); }
/* QuietButton is Button: overrides focus_next only */
static const char *QuietButton_focus_next(void *s, const WidgetVT *vt) { (void)s; (void)vt; return "focus stays"; }

static const LabelledVT Button_vt = { { "Button", Labelled_render, Button_click, Widget_focus_next }, Button_kind, Labelled_text };
static const LabelledVT QuietButton_vt = { { "QuietButton", Labelled_render, Button_click, QuietButton_focus_next }, Button_kind, Labelled_text };
static const LabelledVT Badge_vt = { { "Badge", Labelled_render, Badge_click, Widget_focus_next }, Badge_kind, Badge_text };
static const WidgetVT Slider_vt = { "Slider", Slider_render, Slider_click, Widget_focus_next };

/* ============ (a) two roles: SaveableButton is Widget with a field + forwarding; Saveable is a separate class ============ */
typedef struct SaveableVT SaveableVT;
struct SaveableVT { const char *cls; const char *(*save)(void *, const SaveableVT *); };
typedef struct { char label[32]; } ButtonSaver;
static const char *ButtonSaver_save(void *s, const SaveableVT *vt) {
  static char buf[64];
  (void)vt;
  snprintf(buf, sizeof buf, "button:%s", ((ButtonSaver *)s)->label);
  return buf;
}
static const SaveableVT ButtonSaver_vt = { "ButtonSaver", ButtonSaver_save };
typedef struct { Button button; } SaveableButton;               /* the widget role is a field */
static void SaveableButton_render(void *s, const WidgetVT *vt, int depth) {   /* forwarding: a direct, static call */
  (void)vt;
  Labelled_render(&((SaveableButton *)s)->button, (const WidgetVT *)&Button_vt, depth);
}
static void SaveableButton_click(void *s, const WidgetVT *vt) {
  (void)vt;
  Button_click(&((SaveableButton *)s)->button, (const WidgetVT *)&Button_vt);
}
static const WidgetVT SaveableButton_vt = { "SaveableButton", SaveableButton_render, SaveableButton_click, Widget_focus_next };
static Dyn SaveableButton_as_saveable(SaveableButton *s) {      /* a snapshot, not a view */
  ButtonSaver b;
  snprintf(b.label, sizeof b.label, "%s", s->button.l.label);
  return box(&b, sizeof b, &ButtonSaver_vt);
}

/* ============ (b) subclassing the built-in List ============ */
typedef struct ListVT ListVT;
typedef struct { char *items[16]; int n; } List;
struct ListVT {
  const char *cls;
  void (*push)(void *, const ListVT *, const char *);
  void (*push_all)(void *, const ListVT *, const char **, int);
};
static char *dupstr(const char *x) { char *p = malloc(strlen(x) + 1); strcpy(p, x); return p; }
static void list_append(List *l, const char *x) { l->items[l->n++] = dupstr(x); }   /* the primitive both built-ins use */
static void List_push(void *s, const ListVT *vt, const char *x) { (void)vt; list_append(s, x); }
static void List_push_all(void *s, const ListVT *vt, const char **xs, int n) {
  (void)vt;
  for (int i = 0; i < n; i++) list_append(s, xs[i]);   /* built-ins never call their own overridable push */
}
typedef struct { List l; } LoggedNames;
typedef struct { List l; } LoggedAll;
typedef struct { List l; int n; } CountedNames;
static void LoggedNames_push(void *s, const ListVT *vt, const char *x) {
  printf("  log push %s\n", x);
  List_push(s, vt, x);                                  /* super.push(x): direct */
}
static void LoggedAll_push_all(void *s, const ListVT *vt, const char **xs, int n) {
  for (int i = 0; i < n; i++) vt->push(s, vt, xs[i]);   /* self.push(x): OPEN, through the dynamic vtable */
}
static void CountedNames_push(void *s, const ListVT *vt, const char *x) {
  ((CountedNames *)s)->n += 1;
  LoggedNames_push(s, vt, x);                           /* super.push(x): direct */
}
static const ListVT List_vt = { "List", List_push, List_push_all };
static const ListVT LoggedNames_vt = { "LoggedNames", LoggedNames_push, List_push_all };
static const ListVT LoggedAll_vt = { "LoggedAll", LoggedNames_push, LoggedAll_push_all };
static const ListVT CountedNames_vt = { "CountedNames", CountedNames_push, LoggedAll_push_all };
static void fill(Dyn names, const char **more, int n) {   /* names: dyn List of Str, a borrow */
  const ListVT *vt = names.vt;
  vt->push_all(names.p, vt, more, n);
}
static void show_list(const char *tag, List *l) {
  printf("%s = [", tag);
  for (int i = 0; i < l->n; i++) printf("%s%s", i ? " " : "", l->items[i]);
  printf("]\n");
}

int main(void) {
  printf("== H1 shapes (dyn Shape: describe -> open self-calls name, area) ==\n");
  Circle c = { 1.0 };
  Hexagon h = { 2.0 };
  Rect r = { 2.0, 3.0 };
  Dyn shapes[3] = { box(&c, sizeof c, &Circle_vt), box(&h, sizeof h, &Hexagon_vt), box(&r, sizeof r, &Rect_vt) };
  for (int i = 0; i < 3; i++) { const ShapeVT *vt = shapes[i].vt; vt->describe(shapes[i].p, vt); }
  printf("plain Circle area (direct call, no vtable): %.2f\n", Circle_area(&c, &Circle_vt));

  printf("== H1 widgets (template method; self.focus_next() open) ==\n");
  Button ok = { { "OK" } };
  Button q = { { "Q" } };
  Badge bd = { { "inbox" }, 3 };
  Slider sl = { 3, 10 };
  Dyn ws[4] = { box(&ok, sizeof ok, &Button_vt), box(&sl, sizeof sl, &Slider_vt), box(&bd, sizeof bd, &Badge_vt), box(&q, sizeof q, &QuietButton_vt) };
  for (int i = 0; i < 4; i++) { const WidgetVT *vt = ws[i].vt; printf("render "); vt->render(ws[i].p, vt, 0); }
  { const WidgetVT *vt = ws[0].vt; printf("click OK: "); vt->click(ws[0].p, vt); }
  { const WidgetVT *vt = ws[3].vt; printf("click QuietButton Q: "); vt->click(ws[3].p, vt); }

  printf("== H1 two roles (field + forwarding) ==\n");
  SaveableButton sb = { { { "Save" } } };
  Dyn sw = box(&sb, sizeof sb, &SaveableButton_vt);
  { const WidgetVT *vt = sw.vt; printf("as widget: "); vt->render(sw.p, vt, 0); }
  Dyn sv = SaveableButton_as_saveable(&sb);
  { const SaveableVT *vt = sv.vt; printf("as saveable: %s\n", vt->save(sv.p, vt)); }
  printf("SaveableButton is a Saveable: no (the Saveable role is a separate ButtonSaver object)\n");

  printf("== H1 LoggedNames (subclass of the built-in List) ==\n");
  LoggedNames a = { { { 0 }, 0 } };
  const char *bc[] = { "b", "c" }, *xy[] = { "x", "y" }, *w[] = { "w" };
  printf("a.push(a)\n");
  LoggedNames_push(&a, &LoggedNames_vt, "a");
  printf("a.push_all([b, c])\n");
  LoggedNames_vt.push_all(&a, &LoggedNames_vt, bc, 2);          /* resolves to List.push_all: no log lines */
  show_list("a", &a.l);
  CountedNames cn = { { { 0 }, 0 }, 0 };
  printf("c.push_all([x, y])\n");
  CountedNames_vt.push_all(&cn, &CountedNames_vt, xy, 2);
  printf("c.n = %d\n", cn.n);
  printf("c.push(z)\n");
  CountedNames_push(&cn, &CountedNames_vt, "z");
  printf("c.n = %d\n", cn.n);
  printf("plain List p.push_all([p, q]) (exactly List)\n");
  List pl = { { 0 }, 0 };
  const char *pq[] = { "p", "q" };
  List_vt.push_all(&pl, &List_vt, pq, 2);
  show_list("p", &pl);
  printf("LoggedAll d.push_all([m])\n");
  LoggedAll d = { { { 0 }, 0 } };
  const char *mm[] = { "m" };
  LoggedAll_vt.push_all(&d, &LoggedAll_vt, mm, 1);
  printf("fill(dyn List c, [w])\n");
  Dyn cd = { &cn, &CountedNames_vt };
  fill(cd, w, 1);
  printf("c.n = %d\n", cn.n);
  show_list("c", &cn.l);
  return 0;
}

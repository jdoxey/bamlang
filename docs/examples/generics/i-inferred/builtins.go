package main

// Everything in this file stands in for the language's BUILT-IN generic set
// (List/Map/Optional algorithms). It is not user code and is identical in all
// three options except for the comment on each type-parameter list.

import (
	"cmp"
	"slices"
)

type Optional[T any] struct { // inferred, not written by the user (built-in set)
	v  T
	ok bool
}

func Some[T any](v T) Optional[T] { return Optional[T]{v, true} } // inferred, not written by the user (built-in set)

func None[T any]() Optional[T] { return Optional[T]{} } // inferred, not written by the user (built-in set)

func (o Optional[T]) Get() (T, bool) { return o.v, o.ok }

// Then is the Optional "map" (flat): none stays none.
func Then[T, U any](o Optional[T], f func(T) Optional[U]) Optional[U] { // inferred, not written by the user (built-in set)
	if o.ok {
		return f(o.v)
	}
	return Optional[U]{}
}

func Filter[T any](xs []T, pred func(T) bool) []T { // inferred, not written by the user (built-in set)
	var out []T
	for _, x := range xs {
		if pred(x) {
			out = append(out, x)
		}
	}
	return out
}

func Map[T, U any](xs []T, f func(T) U) []U { // inferred, not written by the user (built-in set)
	out := make([]U, 0, len(xs))
	for _, x := range xs {
		out = append(out, f(x))
	}
	return out
}

func GroupBy[T any, K comparable](xs []T, key func(T) K) map[K][]T { // inferred, not written by the user (built-in set)
	out := map[K][]T{}
	for _, x := range xs {
		out[key(x)] = append(out[key(x)], x)
	}
	return out
}

// MinBy returns the first minimal element in list order.
func MinBy[T any](xs []T, less func(a, b T) bool) T { // inferred, not written by the user (built-in set)
	best := xs[0]
	for _, x := range xs[1:] {
		if less(x, best) {
			best = x
		}
	}
	return best
}

// MaxBy returns the first maximal element in list order.
func MaxBy[T any](xs []T, less func(a, b T) bool) T { // inferred, not written by the user (built-in set)
	best := xs[0]
	for _, x := range xs[1:] {
		if less(best, x) {
			best = x
		}
	}
	return best
}

func SortedKeys[K cmp.Ordered, V any](m map[K]V) []K { // inferred, not written by the user (built-in set)
	keys := make([]K, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}

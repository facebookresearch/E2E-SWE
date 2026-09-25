// Shared includes + helpers for the gtirb WRG per-subsystem test files.
//
// The verifier compiles each subsystem file (test_core.cpp,
// test_module_section.cpp, ...) into its own binary so a compile error
// in one subsystem doesn't cascade to the other subsystems. Every
// subsystem file `#include`s this header so the helpers below stay
// consistent across the split.
//
// This header carries no TEST() definitions — only common declarations,
// includes, and helper templates.

#pragma once

#include <gtest/gtest.h>
#include <gtirb/gtirb.hpp>

#include <algorithm>
#include <array>
#include <boost/endian/conversion.hpp>
#include <cstdint>
#include <iterator>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>

using namespace gtirb;

// -----------------------------------------------------------------------------
// Iteration-yield-type shim.
//
// gtirb v2.3.2's ground-truth iterators yield `T&` (via boost::indirect_iterator
// over `T*` containers). Some agent implementations use `for (auto p : range) {
// ... }` iteration returning `T*` directly. instruction.md pins the yield type
// for a few but not all iteration accessors, so this shim lets test code accept
// either style without a compile cascade.
//
// Usage: replace
//     for (auto& x : container) { by_ptr.insert(&x); }
// with
//     for (auto* x : ptrs_of(container)) { by_ptr.insert(x); }
// -----------------------------------------------------------------------------

// Convert a single iteration element to `T*` regardless of whether the range
// yields `T&` (references) or `T*` (raw pointers).
template <typename Elem>
constexpr auto elem_to_ptr(Elem&& e) {
    using Bare = std::remove_reference_t<Elem>;
    if constexpr (std::is_pointer_v<Bare>) {
        return e;                    // range yielded T* already
    } else {
        return &e;                   // range yielded T& — take address
    }
}

// Collect a range's elements into a std::vector<T*>. Works with any range
// whose iteration yields either T& or T*, giving test code a uniform `T*` set.
template <typename Range>
auto ptrs_of(Range&& r) {
    using Iter = decltype(std::begin(r));
    using RefT = decltype(*std::declval<Iter>());
    using PtrT = std::remove_pointer_t<std::remove_reference_t<RefT>>*;
    std::vector<PtrT> out;
    for (auto&& e : r) {
        out.push_back(elem_to_ptr(std::forward<decltype(e)>(e)));
    }
    return out;
}

// Count elements in a range, independent of iteration yield style.
template <typename Range>
size_t range_size(Range&& r) {
    return static_cast<size_t>(std::distance(std::begin(r), std::end(r)));
}

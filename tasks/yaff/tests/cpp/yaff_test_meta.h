// Shared "schema" meta-traits for the held-out yaff tests. The protoc plugin would
// normally generate these from a .proto; here we hand-write them so the tests drive the
// runtime (Serializer / *Message readers / Array) directly, with no codegen or protobuf.
//
// Meta-trait contract (mirrors what generated code emits):
//   FixedMessage<M>:  M::LIMIT (inline byte size), M::FLAT_OFFSETS[id-1] (field byte offset),
//                     with one trailing sentinel == LIMIT.
//   Flat/DynamicMessage<M>: M::FLAT_OFFSETS (one per field + trailing sentinel == inline size),
//                     M::STATIC_FLAGS[id-1] (1 == field offset is static / never shifted),
//                     M::DELETED_IDS (sorted ids removed in a later schema version).
//   SparseMessage needs no meta to read (it is self-describing on the wire).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <yaff/base.h>

namespace yaffmeta {

// ---- Fixed-layout "Pair" message: two uint64 fields, 16-byte inline region. ----
// id1 @ 0, id2 @ 8, sentinel 16.
struct FixedPair {
    static constexpr size_t LIMIT = 16;
    static constexpr std::array<yaff::FieldOffset, 3> FLAT_OFFSETS = {0, 8, 16};
};

// ---- Flat "Box" message: a single offset field (nested message / array / string). ----
// id1 @ 0 (4-byte offset), sentinel 4.
struct FlatBox {
    static constexpr std::array<yaff::FieldOffset, 2> FLAT_OFFSETS = {0, 4};
    static constexpr std::array<yaff::FieldId, 0> DELETED_IDS = {};
    static constexpr std::array<bool, 1> STATIC_FLAGS = {1};
};

// ---- Flat "Record": mix of scalar widths + presence. Used explicit+sized. ----
// id1 uint64 @0, id2 uint32 @8, id3 uint64 @12, id4 bool @20, id5 uint64 @21, sentinel 29.
// (Identical layout to the upstream TExplicitMetaV1, whose wire size is verified.)
struct RecordV1 {
    static constexpr std::array<yaff::FieldOffset, 6> FLAT_OFFSETS = {0, 8, 12, 20, 21, 29};
    static constexpr std::array<yaff::FieldId, 0> DELETED_IDS = {};
    static constexpr std::array<bool, 5> STATIC_FLAGS = {1, 1, 1, 1, 1};
};

// ---- Evolved "Record": ids 2 and 3 removed, id6 uint32 added. Reads RecordV1 wire. ----
struct RecordV2 {
    static constexpr std::array<yaff::FieldOffset, 7> FLAT_OFFSETS = {0, 8, 8, 8, 9, 17, 21};
    static constexpr std::array<yaff::FieldId, 2> DELETED_IDS = {2, 3};
    static constexpr std::array<bool, 6> STATIC_FLAGS = {1, 1, 1, 0, 0, 0};
};

// ---- Implicit-presence flat "Flags" message (bool + two uint32 + uint64). ----
struct FlagsV1 {
    static constexpr std::array<yaff::FieldOffset, 5> FLAT_OFFSETS = {0, 1, 5, 9, 17};
    static constexpr std::array<yaff::FieldId, 0> DELETED_IDS = {};
    static constexpr std::array<bool, 4> STATIC_FLAGS = {1, 1, 1, 1};
};

// ---- Evolved "Flags": ids 1 and 4 removed (implicit/sized correction path). ----
struct FlagsV2 {
    static constexpr std::array<yaff::FieldOffset, 4> FLAT_OFFSETS = {0, 0, 4, 8};
    static constexpr std::array<yaff::FieldId, 1> DELETED_IDS = {1};
    static constexpr std::array<bool, 3> STATIC_FLAGS = {1, 0, 0};
};

}  // namespace yaffmeta

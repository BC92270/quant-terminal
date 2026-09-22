// Quantum Lab V4.0 exact feasible-state connectivity engine.
//
// This provider-free helper enumerates the complete N=40, K=10 BANDS state
// space and contracts the feasible Hamming-distance-two graph through its
// nine-element cores.  Two feasible ten-subsets are adjacent iff they share
// exactly one nine-subset, so ten incidences per feasible vertex suffice for
// an exact connected-component computation.

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

using i128 = __int128_t;
using u128 = __uint128_t;

constexpr int N = 40;
constexpr int K = 10;
constexpr int GROUPS = 4;
constexpr int FACTORS = 3;
constexpr std::uint64_t EMPTY_KEY = std::numeric_limits<std::uint64_t>::max();

std::uint32_t rotr(std::uint32_t x, std::uint32_t n) {
    return (x >> n) | (x << (32U - n));
}

class Sha256 {
  public:
    Sha256() { reset(); }

    void reset() {
        state_ = {0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
                  0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};
        bit_length_ = 0;
        buffer_length_ = 0;
    }

    void update(const std::uint8_t* data, std::size_t length) {
        for (std::size_t i = 0; i < length; ++i) {
            buffer_[buffer_length_++] = data[i];
            if (buffer_length_ == 64) {
                transform(buffer_.data());
                bit_length_ += 512;
                buffer_length_ = 0;
            }
        }
    }

    void update_u32(std::uint32_t value) {
        std::array<std::uint8_t, 4> bytes{};
        for (int i = 0; i < 4; ++i) {
            bytes[3 - i] = static_cast<std::uint8_t>(value >> (8 * i));
        }
        update(bytes.data(), bytes.size());
    }

    void update_u64(std::uint64_t value) {
        std::array<std::uint8_t, 8> bytes{};
        for (int i = 0; i < 8; ++i) {
            bytes[7 - i] = static_cast<std::uint8_t>(value >> (8 * i));
        }
        update(bytes.data(), bytes.size());
    }

    std::string finish_hex() {
        const std::uint64_t total_bits = bit_length_ + buffer_length_ * 8ULL;
        buffer_[buffer_length_++] = 0x80U;
        if (buffer_length_ > 56) {
            while (buffer_length_ < 64) buffer_[buffer_length_++] = 0;
            transform(buffer_.data());
            buffer_length_ = 0;
        }
        while (buffer_length_ < 56) buffer_[buffer_length_++] = 0;
        for (int i = 7; i >= 0; --i) {
            buffer_[buffer_length_++] = static_cast<std::uint8_t>(total_bits >> (8 * i));
        }
        transform(buffer_.data());

        std::ostringstream out;
        out << std::hex << std::setfill('0');
        for (std::uint32_t word : state_) out << std::setw(8) << word;
        return out.str();
    }

  private:
    void transform(const std::uint8_t* block) {
        static constexpr std::array<std::uint32_t, 64> k = {
            0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
            0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
            0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
            0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
            0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
            0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
            0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
            0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};
        std::array<std::uint32_t, 64> w{};
        for (int i = 0; i < 16; ++i) {
            const int j = i * 4;
            w[i] = (static_cast<std::uint32_t>(block[j]) << 24U) |
                   (static_cast<std::uint32_t>(block[j + 1]) << 16U) |
                   (static_cast<std::uint32_t>(block[j + 2]) << 8U) |
                   static_cast<std::uint32_t>(block[j + 3]);
        }
        for (int i = 16; i < 64; ++i) {
            const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3U);
            const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10U);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        std::uint32_t a=state_[0], b=state_[1], c=state_[2], d=state_[3];
        std::uint32_t e=state_[4], f=state_[5], g=state_[6], h=state_[7];
        for (int i = 0; i < 64; ++i) {
            const std::uint32_t s1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
            const std::uint32_t ch = (e & f) ^ ((~e) & g);
            const std::uint32_t t1 = h + s1 + ch + k[i] + w[i];
            const std::uint32_t s0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
            const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t t2 = s0 + maj;
            h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }
        state_[0]+=a; state_[1]+=b; state_[2]+=c; state_[3]+=d;
        state_[4]+=e; state_[5]+=f; state_[6]+=g; state_[7]+=h;
    }

    std::array<std::uint32_t, 8> state_{};
    std::array<std::uint8_t, 64> buffer_{};
    std::uint64_t bit_length_ = 0;
    std::size_t buffer_length_ = 0;
};

i128 parse_i128(const std::string& text) {
    if (text.empty()) throw std::runtime_error("empty signed integer");
    std::size_t pos = 0;
    bool negative = false;
    if (text[pos] == '+' || text[pos] == '-') {
        negative = text[pos] == '-';
        ++pos;
    }
    if (pos == text.size()) throw std::runtime_error("invalid signed integer");
    u128 value = 0;
    for (; pos < text.size(); ++pos) {
        const char ch = text[pos];
        if (ch < '0' || ch > '9') throw std::runtime_error("invalid signed integer");
        value = value * 10 + static_cast<unsigned>(ch - '0');
    }
    return negative ? -static_cast<i128>(value) : static_cast<i128>(value);
}

std::uint64_t mix64(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

struct Group {
    std::uint64_t mask = 0;
    int lower = 0;
    int upper = 0;
    std::vector<int> indices;
};

struct Instance {
    int seed = 0;
    std::uint64_t witness = 0;
    std::array<Group, GROUPS> groups{};
    std::array<std::array<i128, N>, FACTORS> coefficients{};
    std::array<i128, FACTORS> lower{};
    std::array<i128, FACTORS> upper{};
};

struct LocalSubset {
    std::uint64_t mask = 0;
    int count = 0;
    std::array<i128, FACTORS> sums{};
};

struct HalfSubset {
    std::uint64_t mask = 0;
    std::array<i128, FACTORS> sums{};
};

Instance read_instance() {
    std::string magic;
    if (!(std::cin >> magic) || magic != "QLV40") throw std::runtime_error("invalid input magic");
    Instance instance;
    std::string witness;
    std::cin >> instance.seed >> witness;
    instance.witness = std::stoull(witness, nullptr, 16);
    std::uint64_t union_mask = 0;
    for (int g = 0; g < GROUPS; ++g) {
        std::string mask;
        std::cin >> mask >> instance.groups[g].lower >> instance.groups[g].upper;
        instance.groups[g].mask = std::stoull(mask, nullptr, 16);
        if (union_mask & instance.groups[g].mask) throw std::runtime_error("group masks overlap");
        union_mask |= instance.groups[g].mask;
        for (int bit = 0; bit < N; ++bit) {
            if ((instance.groups[g].mask >> bit) & 1ULL) instance.groups[g].indices.push_back(bit);
        }
        if (instance.groups[g].indices.size() != 10) throw std::runtime_error("each group must contain ten indices");
    }
    if (union_mask != ((1ULL << N) - 1ULL)) throw std::runtime_error("group masks do not partition N=40");
    for (int f = 0; f < FACTORS; ++f) {
        std::string lower, upper;
        std::cin >> lower >> upper;
        instance.lower[f] = parse_i128(lower);
        instance.upper[f] = parse_i128(upper);
        if (instance.lower[f] > instance.upper[f]) throw std::runtime_error("invalid factor interval");
        for (int bit = 0; bit < N; ++bit) {
            std::string value;
            std::cin >> value;
            instance.coefficients[f][bit] = parse_i128(value);
        }
    }
    if (!std::cin) throw std::runtime_error("truncated input");
    return instance;
}

bool exact_feasible(const Instance& instance, std::uint64_t mask) {
    if (__builtin_popcountll(mask) != K || (mask >> N) != 0) return false;
    for (const Group& group : instance.groups) {
        const int count = __builtin_popcountll(mask & group.mask);
        if (count < group.lower || count > group.upper) return false;
    }
    for (int f = 0; f < FACTORS; ++f) {
        i128 sum = 0;
        std::uint64_t bits = mask;
        while (bits) {
            const int bit = __builtin_ctzll(bits);
            bits &= bits - 1;
            sum += instance.coefficients[f][bit];
        }
        if (sum < instance.lower[f] || sum > instance.upper[f]) return false;
    }
    return true;
}

std::vector<LocalSubset> local_subsets(const Instance& instance, int group_index) {
    const Group& group = instance.groups[group_index];
    std::vector<LocalSubset> result;
    for (std::uint32_t local = 0; local < (1U << group.indices.size()); ++local) {
        const int count = __builtin_popcount(local);
        if (count < group.lower || count > group.upper) continue;
        LocalSubset row;
        row.count = count;
        for (std::size_t p = 0; p < group.indices.size(); ++p) {
            if ((local >> p) & 1U) {
                const int bit = group.indices[p];
                row.mask |= 1ULL << bit;
                for (int f = 0; f < FACTORS; ++f) row.sums[f] += instance.coefficients[f][bit];
            }
        }
        result.push_back(row);
    }
    return result;
}

using Buckets = std::array<std::vector<HalfSubset>, K + 1>;

Buckets combine_halves(const std::vector<LocalSubset>& a, const std::vector<LocalSubset>& b) {
    Buckets buckets;
    for (const LocalSubset& left : a) {
        for (const LocalSubset& right : b) {
            const int count = left.count + right.count;
            if (count > K) continue;
            HalfSubset row;
            row.mask = left.mask | right.mask;
            for (int f = 0; f < FACTORS; ++f) row.sums[f] = left.sums[f] + right.sums[f];
            buckets[count].push_back(row);
        }
    }
    return buckets;
}

struct Enumeration {
    std::vector<std::uint64_t> masks;
    std::uint64_t group_candidate_count = 0;
    std::uint64_t primary_interval_candidate_count = 0;
};

Enumeration enumerate_feasible(const Instance& instance,
                               const std::array<int, GROUPS>& order,
                               int primary_factor) {
    std::array<std::vector<LocalSubset>, GROUPS> local{};
    for (int g = 0; g < GROUPS; ++g) local[g] = local_subsets(instance, g);
    Buckets left = combine_halves(local[order[0]], local[order[1]]);
    Buckets right = combine_halves(local[order[2]], local[order[3]]);
    Enumeration result;
    for (int count = 0; count <= K; ++count) {
        auto& rb = right[K - count];
        std::sort(rb.begin(), rb.end(), [primary_factor](const HalfSubset& x, const HalfSubset& y) {
            if (x.sums[primary_factor] != y.sums[primary_factor]) return x.sums[primary_factor] < y.sums[primary_factor];
            return x.mask < y.mask;
        });
        result.group_candidate_count += static_cast<std::uint64_t>(left[count].size()) * rb.size();
        for (const HalfSubset& lhs : left[count]) {
            const i128 minimum = instance.lower[primary_factor] - lhs.sums[primary_factor];
            const i128 maximum = instance.upper[primary_factor] - lhs.sums[primary_factor];
            const auto begin = std::lower_bound(rb.begin(), rb.end(), minimum,
                [primary_factor](const HalfSubset& row, const i128& value) { return row.sums[primary_factor] < value; });
            const auto end = std::upper_bound(rb.begin(), rb.end(), maximum,
                [primary_factor](const i128& value, const HalfSubset& row) { return value < row.sums[primary_factor]; });
            result.primary_interval_candidate_count += static_cast<std::uint64_t>(end - begin);
            for (auto it = begin; it != end; ++it) {
                bool valid = true;
                for (int f = 0; f < FACTORS; ++f) {
                    if (f == primary_factor) continue;
                    const i128 sum = lhs.sums[f] + it->sums[f];
                    if (sum < instance.lower[f] || sum > instance.upper[f]) { valid = false; break; }
                }
                if (valid) result.masks.push_back(lhs.mask | it->mask);
            }
        }
    }
    std::sort(result.masks.begin(), result.masks.end());
    if (std::adjacent_find(result.masks.begin(), result.masks.end()) != result.masks.end()) {
        throw std::runtime_error("enumerator emitted a duplicate state");
    }
    for (std::uint64_t mask : result.masks) {
        if (!exact_feasible(instance, mask)) throw std::runtime_error("enumerator emitted an infeasible state");
    }
    return result;
}

class Dsu {
  public:
    explicit Dsu(std::size_t n) : parent_(n), size_(n, 1) {
        for (std::size_t i = 0; i < n; ++i) parent_[i] = static_cast<std::uint32_t>(i);
    }
    std::uint32_t find(std::uint32_t x) {
        std::uint32_t root = x;
        while (parent_[root] != root) root = parent_[root];
        while (parent_[x] != x) { const std::uint32_t next = parent_[x]; parent_[x] = root; x = next; }
        return root;
    }
    bool unite(std::uint32_t a, std::uint32_t b) {
        a = find(a); b = find(b);
        if (a == b) return false;
        if (size_[a] < size_[b] || (size_[a] == size_[b] && a > b)) std::swap(a, b);
        parent_[b] = a;
        size_[a] += size_[b];
        return true;
    }
  private:
    std::vector<std::uint32_t> parent_;
    std::vector<std::uint32_t> size_;
};

class CoreIndex {
  public:
    explicit CoreIndex(std::size_t expected_vertices) {
        std::size_t capacity = 1024;
        // Empirically conservative initial allocation for this frozen family;
        // correctness does not depend on it because the table grows before a
        // 72% load factor is reached.
        const std::size_t required = expected_vertices * 6;
        while (capacity < required) capacity <<= 1U;
        keys_.assign(capacity, EMPTY_KEY);
        metadata_.assign(capacity, 0);
        mask_ = capacity - 1;
    }
    struct Result {
        bool inserted;
        std::uint32_t first_vertex;
        std::uint32_t previous_occurrences;
    };
    Result insert_or_first(std::uint64_t key, std::uint32_t vertex) {
        if (vertex >= FIRST_MASK) throw std::runtime_error("vertex index exceeds packed core metadata capacity");
        if ((size_ + 1) * 100 >= keys_.size() * 72) grow();
        std::size_t slot = static_cast<std::size_t>(mix64(key)) & mask_;
        while (true) {
            if (keys_[slot] == EMPTY_KEY) {
                keys_[slot] = key;
                metadata_[slot] = vertex | (1U << COUNT_SHIFT);
                ++size_;
                return {true, vertex, 0};
            }
            if (keys_[slot] == key) {
                const std::uint32_t prior = metadata_[slot] >> COUNT_SHIFT;
                if (prior >= 31) throw std::runtime_error("nine-core occurrence bound exceeded");
                const std::uint32_t first = metadata_[slot] & FIRST_MASK;
                metadata_[slot] += (1U << COUNT_SHIFT);
                return {false, first, prior};
            }
            slot = (slot + 1) & mask_;
        }
    }
    std::size_t size() const { return size_; }
    std::size_t capacity() const { return keys_.size(); }
  private:
    static constexpr std::uint32_t COUNT_SHIFT = 26;
    static constexpr std::uint32_t FIRST_MASK = (1U << COUNT_SHIFT) - 1U;
    void grow() {
        std::vector<std::uint64_t> old_keys = std::move(keys_);
        std::vector<std::uint32_t> old_metadata = std::move(metadata_);
        keys_.assign(old_keys.size() * 2, EMPTY_KEY);
        metadata_.assign(old_metadata.size() * 2, 0);
        mask_ = keys_.size() - 1;
        for (std::size_t i = 0; i < old_keys.size(); ++i) {
            if (old_keys[i] == EMPTY_KEY) continue;
            std::size_t slot = static_cast<std::size_t>(mix64(old_keys[i])) & mask_;
            while (keys_[slot] != EMPTY_KEY) slot = (slot + 1) & mask_;
            keys_[slot] = old_keys[i];
            metadata_[slot] = old_metadata[i];
        }
    }
    std::vector<std::uint64_t> keys_;
    std::vector<std::uint32_t> metadata_;
    std::size_t mask_ = 0;
    std::size_t size_ = 0;
};

std::string hex_mask(std::uint64_t mask) {
    std::ostringstream out;
    out << std::hex << std::setw(10) << std::setfill('0') << mask;
    return out.str();
}

void emit_result(const Instance& instance, const Enumeration& enumeration,
                 const std::array<int, GROUPS>& order, int primary_factor,
                 long long enumeration_ms) {
    const std::size_t vertex_count = enumeration.masks.size();
    if (vertex_count == 0) throw std::runtime_error("feasible state set is empty");
    if (!std::binary_search(enumeration.masks.begin(), enumeration.masks.end(), instance.witness)) {
        throw std::runtime_error("authenticated witness missing from feasible enumeration");
    }

    Sha256 enumeration_hash;
    for (std::uint64_t mask : enumeration.masks) enumeration_hash.update_u64(mask);
    const std::string enumeration_sha = enumeration_hash.finish_hex();

    const auto core_start = std::chrono::steady_clock::now();
    Dsu dsu(vertex_count);
    CoreIndex cores(vertex_count);
    Sha256 core_hash;
    Sha256 forest_hash;
    std::uint64_t union_attempts = 0;
    std::uint64_t successful_unions = 0;
    std::uint64_t observed_incidences = 0;
    std::uint64_t exact_edge_count = 0;
    for (std::uint32_t vertex = 0; vertex < vertex_count; ++vertex) {
        std::uint64_t bits = enumeration.masks[vertex];
        while (bits) {
            const int bit = __builtin_ctzll(bits);
            bits &= bits - 1;
            const std::uint64_t core = enumeration.masks[vertex] & ~(1ULL << bit);
            ++observed_incidences;
            core_hash.update_u64(core);
            core_hash.update_u32(vertex);
            const CoreIndex::Result lookup = cores.insert_or_first(core, vertex);
            if (!lookup.inserted) {
                ++union_attempts;
                exact_edge_count += lookup.previous_occurrences;
                if (dsu.unite(vertex, lookup.first_vertex)) {
                    ++successful_unions;
                    forest_hash.update_u64(core);
                    forest_hash.update_u64(enumeration.masks[lookup.first_vertex]);
                    forest_hash.update_u64(enumeration.masks[vertex]);
                }
            }
        }
    }
    const std::string core_sha = core_hash.finish_hex();
    const std::string forest_sha = forest_hash.finish_hex();

    std::unordered_map<std::uint32_t, std::pair<std::uint64_t, std::uint64_t>> components;
    components.reserve(vertex_count / 4 + 1);
    for (std::uint32_t vertex = 0; vertex < vertex_count; ++vertex) {
        const std::uint32_t root = dsu.find(vertex);
        auto [it, inserted] = components.emplace(root, std::make_pair(0ULL, enumeration.masks[vertex]));
        ++it->second.first;
        if (enumeration.masks[vertex] < it->second.second) it->second.second = enumeration.masks[vertex];
    }
    std::vector<std::pair<std::uint64_t, std::uint64_t>> component_rows;
    component_rows.reserve(components.size());
    for (const auto& item : components) component_rows.push_back(item.second);
    std::sort(component_rows.begin(), component_rows.end(), [](const auto& a, const auto& b) { return a.second < b.second; });

    std::unordered_map<std::uint32_t, std::uint64_t> representative_by_root;
    representative_by_root.reserve(components.size() * 2 + 1);
    for (const auto& item : components) representative_by_root.emplace(item.first, item.second.second);
    Sha256 assignment_hash;
    for (std::uint32_t vertex = 0; vertex < vertex_count; ++vertex) {
        assignment_hash.update_u64(enumeration.masks[vertex]);
        assignment_hash.update_u64(representative_by_root.at(dsu.find(vertex)));
    }
    const std::string assignment_sha = assignment_hash.finish_hex();
    const auto core_end = std::chrono::steady_clock::now();
    const auto core_ms = std::chrono::duration_cast<std::chrono::milliseconds>(core_end - core_start).count();

    std::uint64_t largest = 0;
    std::uint64_t smallest = std::numeric_limits<std::uint64_t>::max();
    for (const auto& row : component_rows) { largest = std::max(largest, row.first); smallest = std::min(smallest, row.first); }
    const bool connected = component_rows.size() == 1;

    std::cout << "{";
    std::cout << "\"algorithm\":\"EXHAUSTIVE_GROUP_MITM_PLUS_NINE_CORE_DSU_V1\",";
    std::cout << "\"arithmetic\":\"SIGNED_INT128_EXACT\",";
    std::cout << "\"component_assignment_sha256\":\"" << assignment_sha << "\",";
    std::cout << "\"component_count\":" << component_rows.size() << ',';
    std::cout << "\"component_representatives\":[";
    for (std::size_t i = 0; i < component_rows.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << "{\"mask_hex\":\"" << hex_mask(component_rows[i].second) << "\",\"size\":" << component_rows[i].first << '}';
    }
    std::cout << "],";
    std::cout << "\"connected\":" << (connected ? "true" : "false") << ',';
    std::cout << "\"core_index_capacity\":" << cores.capacity() << ',';
    std::cout << "\"core_index_sha256\":\"" << core_sha << "\",";
    std::cout << "\"core_phase_ms\":" << core_ms << ',';
    std::cout << "\"coverage_complete\":true,";
    std::cout << "\"distinct_nine_cores\":" << cores.size() << ',';
    std::cout << "\"enumeration_ms\":" << enumeration_ms << ',';
    std::cout << "\"enumeration_sha256\":\"" << enumeration_sha << "\",";
    std::cout << "\"exact_state_graph_edge_count\":" << exact_edge_count << ',';
    std::cout << "\"feasible_vertex_count\":" << vertex_count << ',';
    std::cout << "\"forest_sha256\":\"" << forest_sha << "\",";
    std::cout << "\"group_candidate_count\":" << enumeration.group_candidate_count << ',';
    std::cout << "\"group_order\":[" << order[0] << ',' << order[1] << ',' << order[2] << ',' << order[3] << "],";
    std::cout << "\"incidence_invariant_valid\":" << (observed_incidences == vertex_count * K ? "true" : "false") << ',';
    std::cout << "\"largest_component_size\":" << largest << ',';
    std::cout << "\"observed_nine_core_incidences\":" << observed_incidences << ',';
    std::cout << "\"primary_factor\":" << primary_factor << ',';
    std::cout << "\"primary_interval_candidate_count\":" << enumeration.primary_interval_candidate_count << ',';
    std::cout << "\"seed\":" << instance.seed << ',';
    std::cout << "\"smallest_component_size\":" << smallest << ',';
    std::cout << "\"successful_unions\":" << successful_unions << ',';
    std::cout << "\"union_attempts\":" << union_attempts << ',';
    std::cout << "\"union_forest_invariant_valid\":" << (successful_unions + component_rows.size() == vertex_count ? "true" : "false") << ',';
    std::cout << "\"witness_mask_hex\":\"" << hex_mask(instance.witness) << "\"";
    std::cout << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        int mode = 0;
        if (argc > 1) mode = std::stoi(argv[1]);
        if (mode != 0 && mode != 1) throw std::runtime_error("mode must be 0 or 1");
        const Instance instance = read_instance();
        const std::array<int, GROUPS> order = mode == 0
            ? std::array<int, GROUPS>{0, 1, 2, 3}
            : std::array<int, GROUPS>{0, 2, 1, 3};
        const int primary_factor = mode == 0 ? 0 : 1;
        const auto start = std::chrono::steady_clock::now();
        const Enumeration enumeration = enumerate_feasible(instance, order, primary_factor);
        const auto end = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
        emit_result(instance, enumeration, order, primary_factor, elapsed);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "V4.0 connectivity engine error: " << error.what() << '\n';
        return 2;
    }
}

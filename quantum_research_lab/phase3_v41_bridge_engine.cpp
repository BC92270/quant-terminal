// Quantum Lab V4.1 independent exact two-out/two-in bridge auditor.
//
// The program receives one authenticated N=40, K=10 source portfolio and the
// seven exact integer band rows.  It exhausts all C(10,2)*C(30,2)=19,575
// Hamming-distance-four candidates, checks delta arithmetic against a full
// recomputation, and emits a deterministic feasible-neighbour inventory.

#include <algorithm>
#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using i128 = __int128_t;
using u128 = __uint128_t;

constexpr int N = 40;
constexpr int K = 10;
constexpr int ROWS = 7;

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

    void update(const std::string& text) {
        update(reinterpret_cast<const std::uint8_t*>(text.data()), text.size());
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
        static constexpr std::array<std::uint32_t, 64> constants = {
            0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
            0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
            0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
            0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
            0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
            0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
            0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
            0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};
        std::array<std::uint32_t, 64> words{};
        for (int i = 0; i < 16; ++i) {
            const int j = 4 * i;
            words[i] = (static_cast<std::uint32_t>(block[j]) << 24U) |
                       (static_cast<std::uint32_t>(block[j + 1]) << 16U) |
                       (static_cast<std::uint32_t>(block[j + 2]) << 8U) |
                       static_cast<std::uint32_t>(block[j + 3]);
        }
        for (int i = 16; i < 64; ++i) {
            const std::uint32_t s0 = rotr(words[i - 15], 7) ^ rotr(words[i - 15], 18) ^ (words[i - 15] >> 3U);
            const std::uint32_t s1 = rotr(words[i - 2], 17) ^ rotr(words[i - 2], 19) ^ (words[i - 2] >> 10U);
            words[i] = words[i - 16] + s0 + words[i - 7] + s1;
        }
        std::uint32_t a=state_[0], b=state_[1], c=state_[2], d=state_[3];
        std::uint32_t e=state_[4], f=state_[5], g=state_[6], h=state_[7];
        for (int i = 0; i < 64; ++i) {
            const std::uint32_t s1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
            const std::uint32_t choice = (e & f) ^ ((~e) & g);
            const std::uint32_t t1 = h + s1 + choice + constants[i] + words[i];
            const std::uint32_t s0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
            const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t t2 = s0 + majority;
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
    std::size_t position = 0;
    bool negative = false;
    if (text[position] == '+' || text[position] == '-') {
        negative = text[position] == '-';
        ++position;
    }
    if (position == text.size()) throw std::runtime_error("invalid signed integer");
    u128 value = 0;
    for (; position < text.size(); ++position) {
        const char ch = text[position];
        if (ch < '0' || ch > '9') throw std::runtime_error("invalid signed integer");
        value = value * 10 + static_cast<unsigned>(ch - '0');
    }
    return negative ? -static_cast<i128>(value) : static_cast<i128>(value);
}

std::string to_string_i128(i128 value) {
    if (value == 0) return "0";
    const bool negative = value < 0;
    u128 magnitude = negative ? static_cast<u128>(-(value + 1)) + 1 : static_cast<u128>(value);
    std::string result;
    while (magnitude) {
        result.push_back(static_cast<char>('0' + magnitude % 10));
        magnitude /= 10;
    }
    if (negative) result.push_back('-');
    std::reverse(result.begin(), result.end());
    return result;
}

std::string mask_hex(std::uint64_t mask) {
    std::ostringstream out;
    out << std::hex << std::nouppercase << std::setfill('0') << std::setw(10) << mask;
    return out.str();
}

struct Row {
    std::string name;
    i128 lower = 0;
    i128 upper = 0;
    std::array<i128, N> coefficient{};
};

struct Instance {
    int seed = 0;
    std::uint64_t source = 0;
    std::array<Row, ROWS> rows{};
};

Instance read_instance() {
    std::string magic;
    if (!(std::cin >> magic) || magic != "QLV41") throw std::runtime_error("invalid input magic");
    Instance instance;
    std::string source;
    std::cin >> instance.seed >> source;
    instance.source = std::stoull(source, nullptr, 16);
    int row_count = 0;
    std::cin >> row_count;
    if (row_count != ROWS) throw std::runtime_error("expected seven rows");
    for (Row& row : instance.rows) {
        std::string lower, upper;
        std::cin >> row.name >> lower >> upper;
        row.lower = parse_i128(lower);
        row.upper = parse_i128(upper);
        if (row.lower > row.upper) throw std::runtime_error("invalid interval");
        for (i128& coefficient : row.coefficient) {
            std::string value;
            std::cin >> value;
            coefficient = parse_i128(value);
        }
    }
    if (!std::cin) throw std::runtime_error("truncated input");
    return instance;
}

std::array<i128, ROWS> values_for(const Instance& instance, std::uint64_t mask) {
    std::array<i128, ROWS> values{};
    std::uint64_t remaining = mask;
    while (remaining) {
        const int bit = __builtin_ctzll(remaining);
        remaining &= remaining - 1;
        for (int row = 0; row < ROWS; ++row) values[row] += instance.rows[row].coefficient[bit];
    }
    return values;
}

bool feasible(const Instance& instance, std::uint64_t mask, const std::array<i128, ROWS>& values) {
    if ((mask >> N) != 0 || __builtin_popcountll(mask) != K) return false;
    for (int row = 0; row < ROWS; ++row) {
        if (values[row] < instance.rows[row].lower || values[row] > instance.rows[row].upper) return false;
    }
    return true;
}

struct Record {
    std::uint64_t target = 0;
    int removed0 = 0;
    int removed1 = 0;
    int added0 = 0;
    int added1 = 0;
    std::array<i128, ROWS> values{};
};

std::string ledger_line(const Instance& instance, const Record& record, bool is_feasible) {
    std::ostringstream out;
    out << mask_hex(instance.source) << '|' << record.removed0 << ',' << record.removed1
        << '|' << record.added0 << ',' << record.added1 << '|' << mask_hex(record.target) << '|';
    for (int row = 0; row < ROWS; ++row) {
        if (row) out << ',';
        out << to_string_i128(record.values[row]);
    }
    out << '|' << (is_feasible ? '1' : '0') << '\n';
    return out.str();
}

void emit_json(const Instance& instance,
               const std::vector<Record>& records,
               std::size_t audited,
               const std::string& ledger_sha,
               const std::string& feasible_sha) {
    std::cout << '{'
              << "\"algorithm\":\"INDEPENDENT_CPP_INT128_FULL_TWO_SWAP_AUDIT_V1\","
              << "\"audit_universe\":19575,"
              << "\"candidates_audited\":" << audited << ','
              << "\"classification_ledger_sha256\":\"" << ledger_sha << "\","
              << "\"feasible_neighbor_count\":" << records.size() << ','
              << "\"feasible_record_sha256\":\"" << feasible_sha << "\","
              << "\"feasible_records\":[";
    for (std::size_t index = 0; index < records.size(); ++index) {
        if (index) std::cout << ',';
        const Record& record = records[index];
        std::cout << "{\"added\":[" << record.added0 << ',' << record.added1 << "],"
                  << "\"exact_values\":[";
        for (int row = 0; row < ROWS; ++row) {
            if (row) std::cout << ',';
            std::cout << '\"' << to_string_i128(record.values[row]) << '\"';
        }
        std::cout << "],\"removed\":[" << record.removed0 << ',' << record.removed1 << "],"
                  << "\"target_mask_hex\":\"" << mask_hex(record.target) << "\"}";
    }
    std::cout << "],\"seed\":" << instance.seed
              << ",\"source_mask_hex\":\"" << mask_hex(instance.source) << "\"}\n";
}

}  // namespace

int main() {
    try {
        const Instance instance = read_instance();
        const auto source_values = values_for(instance, instance.source);
        if (!feasible(instance, instance.source, source_values)) throw std::runtime_error("source is not exactly feasible");

        std::vector<int> selected;
        std::vector<int> unselected;
        for (int bit = 0; bit < N; ++bit) {
            ((instance.source >> bit) & 1ULL ? selected : unselected).push_back(bit);
        }
        if (selected.size() != K || unselected.size() != N - K) throw std::runtime_error("source cardinality mismatch");

        Sha256 classification_digest;
        Sha256 feasible_digest;
        std::vector<Record> feasible_records;
        std::size_t audited = 0;
        for (std::size_t r0 = 0; r0 < selected.size(); ++r0) {
            for (std::size_t r1 = r0 + 1; r1 < selected.size(); ++r1) {
                for (std::size_t a0 = 0; a0 < unselected.size(); ++a0) {
                    for (std::size_t a1 = a0 + 1; a1 < unselected.size(); ++a1) {
                        Record record;
                        record.removed0 = selected[r0];
                        record.removed1 = selected[r1];
                        record.added0 = unselected[a0];
                        record.added1 = unselected[a1];
                        record.target = instance.source ^ (1ULL << record.removed0) ^ (1ULL << record.removed1)
                                      ^ (1ULL << record.added0) ^ (1ULL << record.added1);
                        for (int row = 0; row < ROWS; ++row) {
                            record.values[row] = source_values[row]
                                - instance.rows[row].coefficient[record.removed0]
                                - instance.rows[row].coefficient[record.removed1]
                                + instance.rows[row].coefficient[record.added0]
                                + instance.rows[row].coefficient[record.added1];
                        }
                        if (record.values != values_for(instance, record.target)) throw std::runtime_error("delta/full recomputation mismatch");
                        const bool is_feasible = feasible(instance, record.target, record.values);
                        const std::string line = ledger_line(instance, record, is_feasible);
                        classification_digest.update(line);
                        if (is_feasible) {
                            feasible_digest.update(line);
                            feasible_records.push_back(record);
                        }
                        ++audited;
                    }
                }
            }
        }
        if (audited != 19575) throw std::runtime_error("candidate universe mismatch");
        emit_json(instance, feasible_records, audited, classification_digest.finish_hex(), feasible_digest.finish_hex());
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

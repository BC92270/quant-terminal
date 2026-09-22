// Quantum Lab V4.3 -- independent reversible Boolean protocol simulator.
//
// This executable intentionally has no provider SDK, filesystem access, or
// non-standard dependency.  It validates the classical action and cleanup
// obligations of the frozen reversible primitives; it is not a state-vector,
// backend, hardware, performance, or quantum-advantage experiment.

#include <algorithm>
#include <cstdint>
#include <exception>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace v43 {

using Bit = std::uint8_t;
using Word = std::uint32_t;
using Count = std::uint64_t;

struct GateCounts {
    Count x = 0;
    Count cx = 0;
    Count ccx = 0;
};

void gate_x(Bit& target, GateCounts* counts = nullptr) {
    target ^= Bit{1};
    if (counts != nullptr) {
        ++counts->x;
    }
}

void gate_cx(const Bit& control, Bit& target, GateCounts* counts = nullptr) {
    target ^= control;
    if (counts != nullptr) {
        ++counts->cx;
    }
}

void gate_ccx(
    const Bit& control_a,
    const Bit& control_b,
    Bit& target,
    GateCounts* counts = nullptr
) {
    target ^= static_cast<Bit>(control_a & control_b);
    if (counts != nullptr) {
        ++counts->ccx;
    }
}

std::vector<Bit> bits_from_word(Word value, int width) {
    std::vector<Bit> bits(static_cast<std::size_t>(width), Bit{0});
    for (int index = 0; index < width; ++index) {
        bits[static_cast<std::size_t>(index)] =
            static_cast<Bit>((value >> index) & Word{1});
    }
    return bits;
}

Word word_from_bits(const std::vector<Bit>& bits) {
    Word value = 0;
    for (std::size_t index = 0; index < bits.size(); ++index) {
        value |= static_cast<Word>(bits[index]) << index;
    }
    return value;
}

// Figure 5 of Cuccaro et al. (no incoming carry), valid here for n >= 4.
// A and the zero carry scratch are restored, B receives A+B modulo 2^n,
// and Z is toggled by the outgoing carry.  The explicit ordering below is
// deliberately independent from the Python materializer.
void cuccaro_full_adder(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& z,
    Bit& carry_scratch,
    GateCounts* counts = nullptr
) {
    const int n = static_cast<int>(a.size());
    if (n < 4 || b.size() != a.size()) {
        throw std::invalid_argument("Cuccaro full adder requires equal widths >= 4");
    }

    for (int i = 1; i < n; ++i) {
        gate_cx(a[static_cast<std::size_t>(i)], b[static_cast<std::size_t>(i)], counts);
    }
    gate_cx(a[1], carry_scratch, counts);

    gate_ccx(a[0], b[0], carry_scratch, counts);
    gate_cx(a[2], a[1], counts);

    gate_ccx(carry_scratch, b[1], a[1], counts);
    gate_cx(a[3], a[2], counts);

    for (int i = 2; i <= n - 3; ++i) {
        gate_ccx(
            a[static_cast<std::size_t>(i - 1)],
            b[static_cast<std::size_t>(i)],
            a[static_cast<std::size_t>(i)],
            counts
        );
        gate_cx(
            a[static_cast<std::size_t>(i + 2)],
            a[static_cast<std::size_t>(i + 1)],
            counts
        );
    }

    gate_ccx(
        a[static_cast<std::size_t>(n - 3)],
        b[static_cast<std::size_t>(n - 2)],
        a[static_cast<std::size_t>(n - 2)],
        counts
    );
    gate_cx(a[static_cast<std::size_t>(n - 1)], z, counts);
    gate_ccx(
        a[static_cast<std::size_t>(n - 2)],
        b[static_cast<std::size_t>(n - 1)],
        z,
        counts
    );

    for (int i = 1; i <= n - 2; ++i) {
        gate_x(b[static_cast<std::size_t>(i)], counts);
    }
    gate_cx(carry_scratch, b[1], counts);
    for (int i = 2; i < n; ++i) {
        gate_cx(
            a[static_cast<std::size_t>(i - 1)],
            b[static_cast<std::size_t>(i)],
            counts
        );
    }

    gate_ccx(
        a[static_cast<std::size_t>(n - 3)],
        b[static_cast<std::size_t>(n - 2)],
        a[static_cast<std::size_t>(n - 2)],
        counts
    );
    for (int i = n - 3; i >= 2; --i) {
        gate_ccx(
            a[static_cast<std::size_t>(i - 1)],
            b[static_cast<std::size_t>(i)],
            a[static_cast<std::size_t>(i)],
            counts
        );
        gate_cx(
            a[static_cast<std::size_t>(i + 2)],
            a[static_cast<std::size_t>(i + 1)],
            counts
        );
        gate_x(b[static_cast<std::size_t>(i + 1)], counts);
    }

    gate_ccx(carry_scratch, b[1], a[1], counts);
    gate_cx(a[3], a[2], counts);
    gate_x(b[2], counts);

    gate_ccx(a[0], b[0], carry_scratch, counts);
    gate_cx(a[2], a[1], counts);
    gate_x(b[1], counts);

    gate_cx(a[1], carry_scratch, counts);
    for (int i = 0; i < n; ++i) {
        gate_cx(a[static_cast<std::size_t>(i)], b[static_cast<std::size_t>(i)], counts);
    }
}

// Cuccaro's modulo-2^n construction: add the low n-1 bits with B[n-1]
// serving as the outgoing-carry target, then complete the high sum bit.
void cuccaro_modular_adder(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& carry_scratch,
    GateCounts* counts = nullptr
) {
    const int n = static_cast<int>(a.size());
    if (n < 5 || b.size() != a.size()) {
        throw std::invalid_argument("Materialized modular adder requires equal widths >= 5");
    }
    std::vector<Bit> a_low(a.begin(), a.end() - 1);
    std::vector<Bit> b_low(b.begin(), b.end() - 1);
    Bit high = b.back();
    cuccaro_full_adder(a_low, b_low, high, carry_scratch, counts);
    gate_cx(a.back(), high, counts);
    std::copy(a_low.begin(), a_low.end(), a.begin());
    std::copy(b_low.begin(), b_low.end(), b.begin());
    b.back() = high;
}

// Carry-prefix portion of the optimized Cuccaro circuit.  Keeping this as an
// explicit gate schedule lets the high-bit primitive undo every work bit.
void carry_prefix_forward(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& carry_scratch,
    GateCounts* counts
) {
    const int n = static_cast<int>(a.size());
    for (int i = 1; i < n; ++i) {
        gate_cx(a[static_cast<std::size_t>(i)], b[static_cast<std::size_t>(i)], counts);
    }
    gate_cx(a[1], carry_scratch, counts);
    gate_ccx(a[0], b[0], carry_scratch, counts);
    gate_cx(a[2], a[1], counts);
    gate_ccx(carry_scratch, b[1], a[1], counts);
    gate_cx(a[3], a[2], counts);
    for (int i = 2; i <= n - 3; ++i) {
        gate_ccx(
            a[static_cast<std::size_t>(i - 1)],
            b[static_cast<std::size_t>(i)],
            a[static_cast<std::size_t>(i)],
            counts
        );
        gate_cx(
            a[static_cast<std::size_t>(i + 2)],
            a[static_cast<std::size_t>(i + 1)],
            counts
        );
    }
    gate_ccx(
        a[static_cast<std::size_t>(n - 3)],
        b[static_cast<std::size_t>(n - 2)],
        a[static_cast<std::size_t>(n - 2)],
        counts
    );
}

void carry_prefix_reverse(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& carry_scratch,
    GateCounts* counts
) {
    const int n = static_cast<int>(a.size());
    gate_ccx(
        a[static_cast<std::size_t>(n - 3)],
        b[static_cast<std::size_t>(n - 2)],
        a[static_cast<std::size_t>(n - 2)],
        counts
    );
    for (int i = n - 3; i >= 2; --i) {
        gate_cx(
            a[static_cast<std::size_t>(i + 2)],
            a[static_cast<std::size_t>(i + 1)],
            counts
        );
        gate_ccx(
            a[static_cast<std::size_t>(i - 1)],
            b[static_cast<std::size_t>(i)],
            a[static_cast<std::size_t>(i)],
            counts
        );
    }
    gate_cx(a[3], a[2], counts);
    gate_ccx(carry_scratch, b[1], a[1], counts);
    gate_cx(a[2], a[1], counts);
    gate_ccx(a[0], b[0], carry_scratch, counts);
    gate_cx(a[1], carry_scratch, counts);
    for (int i = n - 1; i >= 1; --i) {
        gate_cx(a[static_cast<std::size_t>(i)], b[static_cast<std::size_t>(i)], counts);
    }
}

void cuccaro_high_bit_toggle(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& output,
    Bit& carry_scratch,
    GateCounts* counts = nullptr
) {
    const int n = static_cast<int>(a.size());
    if (n < 4 || b.size() != a.size()) {
        throw std::invalid_argument("Cuccaro high-bit primitive requires equal widths >= 4");
    }
    carry_prefix_forward(a, b, carry_scratch, counts);
    gate_cx(a[static_cast<std::size_t>(n - 1)], output, counts);
    gate_ccx(
        a[static_cast<std::size_t>(n - 2)],
        b[static_cast<std::size_t>(n - 1)],
        output,
        counts
    );
    carry_prefix_reverse(a, b, carry_scratch, counts);
}

// The carry of one's-complement(a)+b is exactly the unsigned predicate a<b.
void cuccaro_less_than_toggle(
    std::vector<Bit>& a,
    std::vector<Bit>& b,
    Bit& output,
    Bit& carry_scratch,
    GateCounts* counts = nullptr
) {
    for (Bit& bit : a) {
        gate_x(bit, counts);
    }
    cuccaro_high_bit_toggle(a, b, output, carry_scratch, counts);
    for (Bit& bit : a) {
        gate_x(bit, counts);
    }
}

struct SelectState {
    std::vector<Bit> data;
    std::vector<Bit> remove_coin;
    std::vector<Bit> add_coin;
    std::vector<Bit> target;
    Bit addressed_remove = 0;
    Bit addressed_add = 0;
    Bit difference = 0;
    Bit target_feasible = 0;
    Bit move = 0;
};

SelectState make_select_state(Word data_mask, int n, int remove_index, int add_index) {
    SelectState state;
    state.data = bits_from_word(data_mask, n);
    state.remove_coin.assign(static_cast<std::size_t>(n), Bit{0});
    state.add_coin.assign(static_cast<std::size_t>(n), Bit{0});
    state.target.assign(static_cast<std::size_t>(n), Bit{0});
    state.remove_coin[static_cast<std::size_t>(remove_index)] = 1;
    state.add_coin[static_cast<std::size_t>(add_index)] = 1;
    return state;
}

template <typename FeasiblePredicate>
void toggle_feasibility(
    const std::vector<Bit>& register_bits,
    Bit& output,
    const FeasiblePredicate& feasible
) {
    output ^= static_cast<Bit>(feasible(word_from_bits(register_bits)) ? 1 : 0);
}

void build_candidate(SelectState& state) {
    for (std::size_t i = 0; i < state.data.size(); ++i) {
        gate_cx(state.data[i], state.target[i]);
    }
    for (std::size_t i = 0; i < state.data.size(); ++i) {
        gate_ccx(state.difference, state.remove_coin[i], state.target[i]);
        gate_ccx(state.difference, state.add_coin[i], state.target[i]);
    }
}

void erase_candidate(SelectState& state) {
    for (std::size_t reverse = state.data.size(); reverse > 0; --reverse) {
        const std::size_t i = reverse - 1;
        gate_ccx(state.difference, state.add_coin[i], state.target[i]);
        gate_ccx(state.difference, state.remove_coin[i], state.target[i]);
    }
    for (std::size_t reverse = state.data.size(); reverse > 0; --reverse) {
        const std::size_t i = reverse - 1;
        gate_cx(state.data[i], state.target[i]);
    }
}

template <typename FeasiblePredicate>
void select_step(SelectState& state, const FeasiblePredicate& feasible) {
    const std::size_t n = state.data.size();

    for (std::size_t i = 0; i < n; ++i) {
        gate_ccx(state.remove_coin[i], state.data[i], state.addressed_remove);
        gate_ccx(state.add_coin[i], state.data[i], state.addressed_add);
    }
    gate_cx(state.addressed_remove, state.difference);
    gate_cx(state.addressed_add, state.difference);

    build_candidate(state);
    toggle_feasibility(state.target, state.target_feasible, feasible);
    gate_ccx(state.difference, state.target_feasible, state.move);
    erase_candidate(state);

    for (std::size_t i = 0; i < n; ++i) {
        gate_ccx(state.move, state.remove_coin[i], state.data[i]);
        gate_ccx(state.move, state.add_coin[i], state.data[i]);
    }
    gate_cx(state.move, state.addressed_remove);
    gate_cx(state.move, state.addressed_add);
    gate_ccx(state.difference, state.target_feasible, state.move);

    build_candidate(state);
    toggle_feasibility(state.target, state.target_feasible, feasible);
    erase_candidate(state);

    gate_cx(state.addressed_add, state.difference);
    gate_cx(state.addressed_remove, state.difference);
    for (std::size_t reverse = n; reverse > 0; --reverse) {
        const std::size_t i = reverse - 1;
        gate_ccx(state.add_coin[i], state.data[i], state.addressed_add);
        gate_ccx(state.remove_coin[i], state.data[i], state.addressed_remove);
    }
}

bool zero_register(const std::vector<Bit>& bits) {
    return std::all_of(bits.begin(), bits.end(), [](Bit bit) { return bit == 0; });
}

bool all_select_ancillas_clean(const SelectState& state) {
    return zero_register(state.target) && state.addressed_remove == 0 &&
        state.addressed_add == 0 && state.difference == 0 &&
        state.target_feasible == 0 && state.move == 0;
}

struct ValidationSummary {
    Count full_adder_passed = 0;
    Count modular_adder_passed = 0;
    Count comparator_passed = 0;
    Count promise_select_passed = 0;
    Count promise_roundtrip_passed = 0;
    Count gate_contracts_passed = 0;
    Count gate_contracts_tested = 0;
    Count off_promise_negative_controls_passed = 0;
    Count failures = 0;
    std::string first_failure;

    void failure(const std::string& label) {
        ++failures;
        if (first_failure.empty()) {
            first_failure = label;
        }
    }

    void gate_contract(bool condition, const std::string& label) {
        ++gate_contracts_tested;
        if (condition) {
            ++gate_contracts_passed;
        } else {
            failure(label);
        }
    }
};

void validate_gate_contracts(ValidationSummary& summary) {
    for (int width = 5; width <= 7; ++width) {
        {
            auto a = bits_from_word(0, width);
            auto b = bits_from_word(0, width);
            Bit z = 0;
            Bit scratch = 0;
            GateCounts counts;
            cuccaro_full_adder(a, b, z, scratch, &counts);
            summary.gate_contract(
                counts.ccx == static_cast<Count>(2 * width - 1) &&
                    counts.cx == static_cast<Count>(5 * width - 3) &&
                    counts.x == static_cast<Count>(2 * width - 4),
                "FULL_ADDER_GATE_COUNT_W" + std::to_string(width)
            );
        }
        {
            auto a = bits_from_word(0, width);
            auto b = bits_from_word(0, width);
            Bit scratch = 0;
            GateCounts counts;
            cuccaro_modular_adder(a, b, scratch, &counts);
            summary.gate_contract(
                counts.ccx == static_cast<Count>(2 * width - 3) &&
                    counts.cx == static_cast<Count>(5 * width - 7) &&
                    counts.x == static_cast<Count>(2 * width - 6),
                "MODULAR_ADDER_GATE_COUNT_W" + std::to_string(width)
            );
        }
        {
            auto a = bits_from_word(0, width);
            auto b = bits_from_word(0, width);
            Bit output = 0;
            Bit scratch = 0;
            GateCounts counts;
            cuccaro_high_bit_toggle(a, b, output, scratch, &counts);
            summary.gate_contract(
                counts.ccx == static_cast<Count>(2 * width - 1) &&
                    counts.cx == static_cast<Count>(4 * width - 3) && counts.x == 0,
                "HIGH_BIT_GATE_COUNT_W" + std::to_string(width)
            );
        }
        {
            auto a = bits_from_word(0, width);
            auto b = bits_from_word(0, width);
            Bit output = 0;
            Bit scratch = 0;
            GateCounts counts;
            cuccaro_less_than_toggle(a, b, output, scratch, &counts);
            summary.gate_contract(
                counts.ccx == static_cast<Count>(2 * width - 1) &&
                    counts.cx == static_cast<Count>(4 * width - 3) &&
                    counts.x == static_cast<Count>(2 * width),
                "COMPARATOR_GATE_COUNT_W" + std::to_string(width)
            );
        }
    }
}

void validate_arithmetic_exhaustively(ValidationSummary& summary) {
    for (int width = 5; width <= 7; ++width) {
        const Word modulus = Word{1} << width;
        const Word mask = modulus - 1;
        for (Word a_value = 0; a_value < modulus; ++a_value) {
            for (Word b_value = 0; b_value < modulus; ++b_value) {
                for (Bit initial_z : {Bit{0}, Bit{1}}) {
                    auto a = bits_from_word(a_value, width);
                    auto b = bits_from_word(b_value, width);
                    Bit z = initial_z;
                    Bit scratch = 0;
                    cuccaro_full_adder(a, b, z, scratch);
                    const Word sum = a_value + b_value;
                    const bool ok = word_from_bits(a) == a_value &&
                        word_from_bits(b) == (sum & mask) && scratch == 0 &&
                        z == static_cast<Bit>(initial_z ^ ((sum >> width) & 1U));
                    if (ok) {
                        ++summary.full_adder_passed;
                    } else {
                        summary.failure(
                            "FULL_ADDER_W" + std::to_string(width) + "_A" +
                            std::to_string(a_value) + "_B" + std::to_string(b_value)
                        );
                    }

                    auto compare_a = bits_from_word(a_value, width);
                    auto compare_b = bits_from_word(b_value, width);
                    Bit compare_output = initial_z;
                    Bit compare_scratch = 0;
                    cuccaro_less_than_toggle(
                        compare_a,
                        compare_b,
                        compare_output,
                        compare_scratch
                    );
                    const bool compare_ok = word_from_bits(compare_a) == a_value &&
                        word_from_bits(compare_b) == b_value && compare_scratch == 0 &&
                        compare_output ==
                            static_cast<Bit>(initial_z ^ (a_value < b_value ? 1U : 0U));
                    if (compare_ok) {
                        ++summary.comparator_passed;
                    } else {
                        summary.failure(
                            "COMPARATOR_W" + std::to_string(width) + "_A" +
                            std::to_string(a_value) + "_B" + std::to_string(b_value)
                        );
                    }
                }

                auto modular_a = bits_from_word(a_value, width);
                auto modular_b = bits_from_word(b_value, width);
                Bit modular_scratch = 0;
                cuccaro_modular_adder(modular_a, modular_b, modular_scratch);
                const bool modular_ok = word_from_bits(modular_a) == a_value &&
                    word_from_bits(modular_b) == ((a_value + b_value) & mask) &&
                    modular_scratch == 0;
                if (modular_ok) {
                    ++summary.modular_adder_passed;
                } else {
                    summary.failure(
                        "MODULAR_ADDER_W" + std::to_string(width) + "_A" +
                        std::to_string(a_value) + "_B" + std::to_string(b_value)
                    );
                }
            }
        }
    }
}

bool n4_fixture_feasible(Word mask) {
    const unsigned low_pair = static_cast<unsigned>((mask & Word{0b0011}));
    const unsigned high_pair = static_cast<unsigned>((mask & Word{0b1100}) >> 2);
    const auto one_hot_two_bits = [](unsigned value) {
        return value == 1U || value == 2U;
    };
    return one_hot_two_bits(low_pair) && one_hot_two_bits(high_pair);
}

void validate_promise_select_exhaustively(ValidationSummary& summary) {
    for (Word source = 0; source < 16; ++source) {
        if (!n4_fixture_feasible(source)) {
            continue;
        }
        for (int remove_index = 0; remove_index < 4; ++remove_index) {
            for (int add_index = 0; add_index < 4; ++add_index) {
                SelectState state = make_select_state(source, 4, remove_index, add_index);
                const Bit difference = static_cast<Bit>(
                    ((source >> remove_index) & 1U) ^ ((source >> add_index) & 1U)
                );
                Word candidate = source;
                if (difference != 0) {
                    candidate ^= (Word{1} << remove_index);
                    candidate ^= (Word{1} << add_index);
                }
                const Word expected =
                    difference != 0 && n4_fixture_feasible(candidate) ? candidate : source;

                select_step(state, n4_fixture_feasible);
                const bool first_ok = word_from_bits(state.data) == expected &&
                    all_select_ancillas_clean(state);
                if (first_ok) {
                    ++summary.promise_select_passed;
                } else {
                    summary.failure(
                        "PROMISE_SELECT_SOURCE" + std::to_string(source) + "_R" +
                        std::to_string(remove_index) + "_A" + std::to_string(add_index)
                    );
                }

                select_step(state, n4_fixture_feasible);
                const bool roundtrip_ok = word_from_bits(state.data) == source &&
                    all_select_ancillas_clean(state);
                if (roundtrip_ok) {
                    ++summary.promise_roundtrip_passed;
                } else {
                    summary.failure(
                        "PROMISE_ROUNDTRIP_SOURCE" + std::to_string(source) + "_R" +
                        std::to_string(remove_index) + "_A" + std::to_string(add_index)
                    );
                }
            }
        }
    }
}

struct OffPromiseWitness {
    std::string status;
    Word final_data = 0;
    Bit retained_feasibility_flag = 0;
    bool other_ancillas_clean = false;
};

OffPromiseWitness validate_required_off_promise_witness(ValidationSummary& summary) {
    // N=2, K=1; only |01> is admitted.  |10> is deliberately outside the
    // promise.  The selected swap reaches |01>, but reverse cleanup queries
    // the inadmissible source |10>, so its retained feasibility flag is 1.
    const auto only_01_is_feasible = [](Word mask) { return mask == Word{0b01}; };
    SelectState state = make_select_state(Word{0b10}, 2, 1, 0);
    select_step(state, only_01_is_feasible);

    const bool other_ancillas_clean = zero_register(state.target) &&
        state.addressed_remove == 0 && state.addressed_add == 0 &&
        state.difference == 0 && state.move == 0;
    const bool detected = word_from_bits(state.data) == Word{0b01} &&
        state.target_feasible == 1 && other_ancillas_clean;
    if (detected) {
        ++summary.off_promise_negative_controls_passed;
    } else {
        summary.failure("OFF_PROMISE_WITNESS_NOT_DETECTED");
    }

    return OffPromiseWitness{
        detected ? "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"
                 : "OFF_PROMISE_NEGATIVE_CONTROL_NOT_DETECTED",
        word_from_bits(state.data),
        state.target_feasible,
        other_ancillas_clean,
    };
}

std::string binary_mask(Word value, int width) {
    std::string result;
    result.reserve(static_cast<std::size_t>(width));
    for (int bit = width - 1; bit >= 0; --bit) {
        result.push_back(((value >> bit) & Word{1}) != 0 ? '1' : '0');
    }
    return result;
}

std::string json_escape(const std::string& value) {
    std::ostringstream escaped;
    for (const unsigned char character : value) {
        switch (character) {
            case '\"': escaped << "\\\""; break;
            case '\\': escaped << "\\\\"; break;
            case '\b': escaped << "\\b"; break;
            case '\f': escaped << "\\f"; break;
            case '\n': escaped << "\\n"; break;
            case '\r': escaped << "\\r"; break;
            case '\t': escaped << "\\t"; break;
            default:
                if (character < 0x20U) {
                    const char* digits = "0123456789abcdef";
                    escaped << "\\u00" << digits[(character >> 4) & 0x0fU]
                            << digits[character & 0x0fU];
                } else {
                    escaped << static_cast<char>(character);
                }
        }
    }
    return escaped.str();
}

void emit_canonical_json(
    const ValidationSummary& summary,
    const OffPromiseWitness& witness
) {
    const Count arithmetic_passed = summary.full_adder_passed +
        summary.modular_adder_passed + summary.comparator_passed;
    const Count primary_passed = arithmetic_passed + summary.promise_select_passed +
        summary.off_promise_negative_controls_passed;
    const bool passed = summary.failures == 0;

    std::cout
        << "{\"artifact_type\":\"QUANTUM_LAB_V4_3_INDEPENDENT_REVERSIBLE_BOOLEAN_SIMULATION\""
        << ",\"claim_boundary\":{\"hardware_executable\":false,\"provider_calls\":0"
        << ",\"qpu_jobs\":0,\"qpu_jobs_submitted\":0"
        << ",\"quantum_advantage_claimed\":false,\"research_classification\":\"RESEARCH_ONLY\"}"
        << ",\"decision\":\""
        << (passed ? "V43_INDEPENDENT_REVERSIBLE_BOOLEAN_SIMULATION_PASSED"
                   : "V43_INDEPENDENT_REVERSIBLE_BOOLEAN_SIMULATION_FAILED")
        << "\""
        << ",\"execution_boundary\":{\"external_dependencies\":0,\"filesystem_writes\":0"
        << ",\"network_calls\":0}"
        << ",\"failure_count\":" << summary.failures
        << ",\"first_failure\":";
    if (summary.first_failure.empty()) {
        std::cout << "null";
    } else {
        std::cout << "\"" << json_escape(summary.first_failure) << "\"";
    }
    std::cout
        << ",\"negative_control\":{\"K\":1,\"add_bit\":0,\"cleanup_accepted\":false"
        << ",\"feasible_set\":[\"01\"],\"final_data\":\""
        << binary_mask(witness.final_data, 2) << "\",\"n\":2"
        << ",\"other_ancillas_clean\":" << (witness.other_ancillas_clean ? "true" : "false")
        << ",\"remove_bit\":1,\"retained_feasibility_flag\":"
        << static_cast<unsigned>(witness.retained_feasibility_flag)
        << ",\"start\":\"10\",\"status\":\"" << witness.status
        << "\",\"target\":\"01\"}"
        << ",\"pass_counts\":{\"arithmetic_cases\":" << arithmetic_passed
        << ",\"cuccaro_full_adder_cases\":" << summary.full_adder_passed
        << ",\"cuccaro_modular_adder_cases\":" << summary.modular_adder_passed
        << ",\"gate_count_contracts\":" << summary.gate_contracts_passed
        << ",\"high_bit_comparator_cases\":" << summary.comparator_passed
        << ",\"off_promise_negative_controls\":"
        << summary.off_promise_negative_controls_passed
        << ",\"promise_select_cases\":" << summary.promise_select_passed
        << ",\"promise_select_roundtrips\":" << summary.promise_roundtrip_passed
        << ",\"total_primary_cases\":" << primary_passed << "}"
        << ",\"schema_version\":\"1.0\""
        << ",\"status\":\"" << (passed ? "PASS" : "FAIL") << "\""
        << ",\"test_counts\":{\"gate_count_contracts\":"
        << summary.gate_contracts_tested
        << ",\"materialized_widths\":[5,6,7],\"promise_fixture_n\":4}"
        << ",\"valid\":" << (passed ? "true" : "false")
        << "}\n";
}

}  // namespace v43

int main() {
    v43::ValidationSummary summary;
    v43::OffPromiseWitness witness;
    try {
        v43::validate_gate_contracts(summary);
        v43::validate_arithmetic_exhaustively(summary);
        v43::validate_promise_select_exhaustively(summary);
        witness = v43::validate_required_off_promise_witness(summary);
    } catch (const std::exception& error) {
        summary.failure(std::string("EXCEPTION:") + error.what());
        witness.status = "OFF_PROMISE_NEGATIVE_CONTROL_NOT_RUN";
    }
    v43::emit_canonical_json(summary, witness);
    return summary.failures == 0 ? 0 : 1;
}

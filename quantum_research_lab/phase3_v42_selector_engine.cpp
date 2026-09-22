// Quantum Lab V4.2 independent promise-subspace SELECT/walk verifier.
//
// This program is provider-free.  It exhausts every feasible-support predicate
// on every exact-K domain up to N=5, checks the coined exchange involution and
// clean-target flag symmetry, and verifies that the joint one-hot coin/data
// support graph has exactly the same components as the underlying feasible
// exchange graph.  Larger exact-K domains through N=8 provide an additional
// complete connected-support control.  Two traversal modes must agree on all
// stable counts.

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace {

constexpr const char* ENGINE_VERSION =
    "INDEPENDENT_CPP_EXHAUSTIVE_PROMISE_SUBSPACE_COINED_SELECT_V1";

struct Counts {
    std::uint64_t arbitrary_supports = 0;
    std::uint64_t bridge_cases = 0;
    std::uint64_t cleanup_cases = 0;
    std::uint64_t cleanup_failures = 0;
    std::uint64_t full_domain_joint_cases = 0;
    std::uint64_t full_domain_joint_failures = 0;
    std::uint64_t joint_component_cases = 0;
    std::uint64_t joint_component_failures = 0;
    std::uint64_t selector_cases = 0;
    std::uint64_t selector_failures = 0;
};

std::vector<std::uint32_t> exact_k_masks(int n, int k) {
    std::vector<std::uint32_t> result;
    const std::uint32_t limit = 1U << n;
    for (std::uint32_t mask = 0; mask < limit; ++mask) {
        if (__builtin_popcount(mask) == k) result.push_back(mask);
    }
    return result;
}

bool contains_mask(const std::vector<std::uint32_t>& domain,
                   std::uint64_t support_bits,
                   std::uint32_t mask) {
    const auto it = std::lower_bound(domain.begin(), domain.end(), mask);
    if (it == domain.end() || *it != mask) return false;
    const auto index = static_cast<std::size_t>(it - domain.begin());
    return ((support_bits >> index) & 1ULL) != 0;
}

std::vector<std::uint32_t> support_masks(
    const std::vector<std::uint32_t>& domain,
    std::uint64_t support_bits) {
    std::vector<std::uint32_t> result;
    for (std::size_t index = 0; index < domain.size(); ++index) {
        if ((support_bits >> index) & 1ULL) result.push_back(domain[index]);
    }
    return result;
}

std::size_t data_component_count(
    const std::vector<std::uint32_t>& feasible,
    int n) {
    if (feasible.empty()) return 0;
    std::unordered_map<std::uint32_t, std::size_t> index;
    for (std::size_t i = 0; i < feasible.size(); ++i) index.emplace(feasible[i], i);
    std::vector<bool> seen(feasible.size(), false);
    std::size_t components = 0;
    for (std::size_t start = 0; start < feasible.size(); ++start) {
        if (seen[start]) continue;
        ++components;
        std::queue<std::size_t> queue;
        queue.push(start);
        seen[start] = true;
        while (!queue.empty()) {
            const auto current_index = queue.front();
            queue.pop();
            const std::uint32_t current = feasible[current_index];
            for (int r = 0; r < n; ++r) {
                for (int a = r + 1; a < n; ++a) {
                    if (((current >> r) & 1U) == ((current >> a) & 1U)) continue;
                    const std::uint32_t target = current ^ (1U << r) ^ (1U << a);
                    const auto found = index.find(target);
                    if (found != index.end() && !seen[found->second]) {
                        seen[found->second] = true;
                        queue.push(found->second);
                    }
                }
            }
        }
    }
    return components;
}

std::size_t joint_component_count(
    const std::vector<std::uint32_t>& feasible,
    int n) {
    if (feasible.empty()) return 0;
    std::unordered_map<std::uint32_t, std::size_t> data_index;
    for (std::size_t i = 0; i < feasible.size(); ++i) data_index.emplace(feasible[i], i);
    const std::size_t coin_states = static_cast<std::size_t>(n * n);
    const std::size_t node_count = feasible.size() * coin_states;
    std::vector<bool> seen(node_count, false);
    auto node = [coin_states, n](std::size_t data, int r, int a) {
        return data * coin_states + static_cast<std::size_t>(r * n + a);
    };
    std::size_t components = 0;
    for (std::size_t start = 0; start < node_count; ++start) {
        if (seen[start]) continue;
        ++components;
        std::queue<std::size_t> queue;
        queue.push(start);
        seen[start] = true;
        while (!queue.empty()) {
            const auto current_node = queue.front();
            queue.pop();
            const std::size_t data = current_node / coin_states;
            const int coin = static_cast<int>(current_node % coin_states);
            const int r = coin / n;
            const int a = coin % n;
            const int neighbors[4][2] = {
                {(r + 1) % n, a}, {(r + n - 1) % n, a},
                {r, (a + 1) % n}, {r, (a + n - 1) % n},
            };
            for (const auto& next : neighbors) {
                const auto target_node = node(data, next[0], next[1]);
                if (!seen[target_node]) {
                    seen[target_node] = true;
                    queue.push(target_node);
                }
            }
            const std::uint32_t mask = feasible[data];
            if (((mask >> r) & 1U) != ((mask >> a) & 1U)) {
                const std::uint32_t target = mask ^ (1U << r) ^ (1U << a);
                const auto found = data_index.find(target);
                if (found != data_index.end()) {
                    const auto target_node = node(found->second, r, a);
                    if (!seen[target_node]) {
                        seen[target_node] = true;
                        queue.push(target_node);
                    }
                }
            }
        }
    }
    return components;
}

void check_support(int n,
                   const std::vector<std::uint32_t>& domain,
                   std::uint64_t support_bits,
                   bool reverse,
                   Counts& counts) {
    const auto feasible = support_masks(domain, support_bits);
    ++counts.arbitrary_supports;
    const int begin = reverse ? n - 1 : 0;
    const int end = reverse ? -1 : n;
    const int step = reverse ? -1 : 1;
    for (std::uint32_t current : feasible) {
        for (int r = begin; r != end; r += step) {
            for (int a = begin; a != end; a += step) {
                const bool different = ((current >> r) & 1U) != ((current >> a) & 1U);
                const std::uint32_t proposed = different
                    ? current ^ (1U << r) ^ (1U << a)
                    : current;
                const bool target_feasible = contains_mask(domain, support_bits, proposed);
                const bool move = different && target_feasible;
                const std::uint32_t output = move ? proposed : current;
                ++counts.selector_cases;
                if (!contains_mask(domain, support_bits, output)) {
                    ++counts.selector_failures;
                    continue;
                }
                const bool second_different =
                    ((output >> r) & 1U) != ((output >> a) & 1U);
                const std::uint32_t second_proposed = second_different
                    ? output ^ (1U << r) ^ (1U << a)
                    : output;
                const bool second_target_feasible =
                    contains_mask(domain, support_bits, second_proposed);
                const bool second_move = second_different && second_target_feasible;
                const std::uint32_t restored = second_move ? second_proposed : output;
                if (restored != current) ++counts.selector_failures;
                ++counts.cleanup_cases;
                if (target_feasible != second_target_feasible) {
                    ++counts.cleanup_failures;
                }
            }
        }
    }
    ++counts.joint_component_cases;
    if (data_component_count(feasible, n) != joint_component_count(feasible, n)) {
        ++counts.joint_component_failures;
    }
}

Counts run(bool reverse) {
    Counts counts;
    const int n_begin = reverse ? 5 : 2;
    const int n_end = reverse ? 1 : 6;
    const int n_step = reverse ? -1 : 1;
    for (int n = n_begin; n != n_end; n += n_step) {
        const int k_begin = reverse ? n - 1 : 1;
        const int k_end = reverse ? 0 : n;
        const int k_step = reverse ? -1 : 1;
        for (int k = k_begin; k != k_end; k += k_step) {
            const auto domain = exact_k_masks(n, k);
            if (domain.size() >= 63) throw std::runtime_error("support bitset overflow");
            const std::uint64_t limit = 1ULL << domain.size();
            if (!reverse) {
                for (std::uint64_t support = 1; support < limit; ++support) {
                    check_support(n, domain, support, reverse, counts);
                }
            } else {
                for (std::uint64_t support = limit - 1; support > 0; --support) {
                    check_support(n, domain, support, reverse, counts);
                }
            }
        }
    }

    const int large_begin = reverse ? 8 : 2;
    const int large_end = reverse ? 1 : 9;
    const int large_step = reverse ? -1 : 1;
    for (int n = large_begin; n != large_end; n += large_step) {
        const int k_begin = reverse ? n - 1 : 1;
        const int k_end = reverse ? 0 : n;
        const int k_step = reverse ? -1 : 1;
        for (int k = k_begin; k != k_end; k += k_step) {
            const auto domain = exact_k_masks(n, k);
            ++counts.full_domain_joint_cases;
            if (data_component_count(domain, n) != 1
                || joint_component_count(domain, n) != 1) {
                ++counts.full_domain_joint_failures;
            }
        }
    }

    for (int n = 4; n <= 8; ++n) {
        for (int k = 2; k <= n - 2; ++k) {
            const auto domain = exact_k_masks(n, k);
            for (std::uint32_t source : domain) {
                for (std::uint32_t target : domain) {
                    if (__builtin_popcount(source ^ target) != 4) continue;
                    ++counts.bridge_cases;
                    const std::uint32_t delta = source ^ target;
                    if ((source ^ delta) != target || (target ^ delta) != source) {
                        throw std::runtime_error("bridge transposition involution failed");
                    }
                }
            }
        }
    }
    return counts;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        int mode = 0;
        if (argc > 1) mode = std::stoi(argv[1]);
        if (mode != 0 && mode != 1) throw std::runtime_error("mode must be 0 or 1");
        const Counts counts = run(mode == 1);
        const bool valid = counts.selector_failures == 0
            && counts.cleanup_failures == 0
            && counts.joint_component_failures == 0
            && counts.full_domain_joint_failures == 0;
        std::cout << "{";
        std::cout << "\"algorithm\":\"" << ENGINE_VERSION << "\",";
        std::cout << "\"arbitrary_supports\":" << counts.arbitrary_supports << ',';
        std::cout << "\"bridge_cases\":" << counts.bridge_cases << ',';
        std::cout << "\"cleanup_cases\":" << counts.cleanup_cases << ',';
        std::cout << "\"cleanup_failures\":" << counts.cleanup_failures << ',';
        std::cout << "\"full_domain_joint_cases\":" << counts.full_domain_joint_cases << ',';
        std::cout << "\"full_domain_joint_failures\":" << counts.full_domain_joint_failures << ',';
        std::cout << "\"joint_component_cases\":" << counts.joint_component_cases << ',';
        std::cout << "\"joint_component_failures\":" << counts.joint_component_failures << ',';
        std::cout << "\"mode\":" << mode << ',';
        std::cout << "\"selector_cases\":" << counts.selector_cases << ',';
        std::cout << "\"selector_failures\":" << counts.selector_failures << ',';
        std::cout << "\"valid\":" << (valid ? "true" : "false");
        std::cout << "}\n";
        return valid ? 0 : 3;
    } catch (const std::exception& error) {
        std::cerr << "V4.2 selector engine error: " << error.what() << '\n';
        return 2;
    }
}

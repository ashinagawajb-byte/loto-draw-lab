// Exact same 32-bit Mulberry32/Fisher-Yates sequence as worker.py.
// Usage: ./seed_scan GAME START COUNT MAIN_CSV BONUS_CSV
// Prints exact-match seeds only, one per line. No network or secrets.
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

static std::vector<int> parse_numbers(const std::string& s) {
    std::vector<int> out;
    std::size_t pos = 0;
    while (pos < s.size()) {
        const auto end = s.find(',', pos);
        const auto value = s.substr(pos, end == std::string::npos ? end : end - pos);
        if (value.empty()) throw std::invalid_argument("empty number");
        std::size_t consumed = 0;
        int number = std::stoi(value, &consumed);
        if (consumed != value.size()) throw std::invalid_argument("bad number");
        out.push_back(number);
        if (end == std::string::npos) break;
        pos = end + 1;
    }
    return out;
}

static uint64_t mask_for(const std::vector<int>& numbers, int range, int expected) {
    if (static_cast<int>(numbers.size()) != expected) throw std::invalid_argument("wrong number count");
    uint64_t mask = 0;
    for (int value : numbers) {
        if (value < 1 || value > range) throw std::invalid_argument("number out of range");
        const uint64_t bit = uint64_t{1} << value;
        if (mask & bit) throw std::invalid_argument("duplicate number");
        mask |= bit;
    }
    return mask;
}
static uint32_t next_random(uint32_t& state) {
    state += 0x6D2B79F5u;
    uint32_t t = state;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + ((t ^ (t >> 7)) * (t | 61u));
    return t ^ (t >> 14);
}
static bool exact_match(int n, int k, int bonus_count, uint64_t main_mask,
                        uint64_t bonus_mask, uint32_t seed) {
    std::array<int, 44> balls{};
    for (int i = 0; i < n; ++i) balls[i] = i + 1;
    uint32_t state = seed;
    for (int i = n - 1; i > 0; --i) {
        const uint32_t random = next_random(state);
        // This is exactly floor((random / 2^32) * (i+1)).
        const uint32_t j = static_cast<uint32_t>((uint64_t{random} * (i + 1)) >> 32);
        const int hold = balls[i];
        balls[i] = balls[j];
        balls[j] = hold;
    }
    uint64_t got_main = 0, got_bonus = 0;
    for (int i = 0; i < k; ++i) got_main |= uint64_t{1} << balls[i];
    if (got_main != main_mask) return false;
    for (int i = k; i < k + bonus_count; ++i) got_bonus |= uint64_t{1} << balls[i];
    return got_bonus == bonus_mask;
}

int main(int argc, char** argv) {
    try {
        if (argc != 6) throw std::invalid_argument("usage: seed_scan GAME START COUNT MAIN_CSV BONUS_CSV");
        const std::string game_arg = argv[1];
        if (game_arg != "6" && game_arg != "7") throw std::invalid_argument("game must be 6 or 7");
        const int game = std::stoi(game_arg), n = game == 6 ? 43 : 37;
        const int k = game, b = game == 6 ? 1 : 2;
        std::size_t length = 0;
        const auto start = std::stoull(argv[2], &length);
        if (length != std::string(argv[2]).size() || start > UINT32_MAX) throw std::invalid_argument("invalid start");
        length = 0;
        const auto count = std::stoull(argv[3], &length);
        if (length != std::string(argv[3]).size() || count > (uint64_t{1} << 32) - start)
            throw std::invalid_argument("invalid count");
        const auto main = parse_numbers(argv[4]);
        const auto bonus = parse_numbers(argv[5]);
        const auto main_mask = mask_for(main, n, k), bonus_mask = mask_for(bonus, n, b);
        if (main_mask & bonus_mask) throw std::invalid_argument("main and bonus overlap");
        for (uint64_t offset = 0; offset < count; ++offset) {
            const auto seed = static_cast<uint32_t>(start + offset);
            if (exact_match(n, k, b, main_mask, bonus_mask, seed)) std::cout << seed << '\n';
        }
    } catch (const std::exception& ex) {
        std::cerr << "seed_scan: " << ex.what() << '\n';
        return 2;
    }
}

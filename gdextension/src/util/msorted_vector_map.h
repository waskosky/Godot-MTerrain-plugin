/**************************************************************************/
/*  msorted_vector_map.h                                                  */
/**************************************************************************/
/* Copyright (c) 2014-present Godot Engine contributors.                  */
/* Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.                  */
/*                                                                        */
/* Permission is hereby granted, free of charge, to any person obtaining  */
/* a copy of this software and associated documentation files (the        */
/* "Software"), to deal in the Software without restriction, including  */
/* without limitation the rights to use, copy, modify, merge, publish,    */
/* distribute, sublicense, and/or sell copies of the Software, and to     */
/* permit persons to whom the Software is furnished to do so, subject to  */
/* the following conditions:                                              */
/*                                                                        */
/* The above copyright notice and this permission notice shall be         */
/* included in all copies or substantial portions of the Software.        */
/*                                                                        */
/* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,        */
/* EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF     */
/* MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. */
/* IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY   */
/* CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,   */
/* TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE      */
/* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                 */
/**************************************************************************/

#pragma once

#include <functional>

#include <godot_cpp/templates/vector.hpp>

namespace godot {

// Godot 4.7 removed the internal VMap container from godot-cpp. MTerrain still
// needs its stable, sorted, index-addressable behavior for a few native/editor
// data structures, so this repository-owned replacement keeps only the API
// those consumers use. New runtime code should prefer HashMap or RBMap unless
// contiguous sorted storage is a measured requirement.
template <typename Key, typename Value>
class MSortedVectorMap {
public:
	struct Pair {
		Key key;
		Value value;

		Pair() = default;
		Pair(const Key &p_key, const Value &p_value) :
				key(p_key), value(p_value) {}
	};

private:
	Vector<Pair> pairs;

	int find_insertion_position(const Key &p_key, bool &r_exact) const {
		r_exact = false;
		if (pairs.is_empty()) {
			return 0;
		}

		int low = 0;
		int high = static_cast<int>(pairs.size()) - 1;
		int middle = 0;
		while (low <= high) {
			middle = (low + high) / 2;
			if (std::less<Key>{}(p_key, pairs[middle].key)) {
				high = middle - 1;
			} else if (std::less<Key>{}(pairs[middle].key, p_key)) {
				low = middle + 1;
			} else {
				r_exact = true;
				return middle;
			}
		}
		if (std::less<Key>{}(pairs[middle].key, p_key)) {
			middle++;
		}
		return middle;
	}

	int find_exact(const Key &p_key) const {
		if (pairs.is_empty()) {
			return -1;
		}

		int low = 0;
		int high = static_cast<int>(pairs.size()) - 1;
		while (low <= high) {
			const int middle = (low + high) / 2;
			if (std::less<Key>{}(p_key, pairs[middle].key)) {
				high = middle - 1;
			} else if (std::less<Key>{}(pairs[middle].key, p_key)) {
				low = middle + 1;
			} else {
				return middle;
			}
		}
		return -1;
	}

public:
	int insert(const Key &p_key, const Value &p_value) {
		bool exact = false;
		const int position = find_insertion_position(p_key, exact);
		if (exact) {
			pairs.write[position].value = p_value;
			return position;
		}
		pairs.insert(position, Pair(p_key, p_value));
		return position;
	}

	bool has(const Key &p_key) const { return find_exact(p_key) != -1; }

	void erase(const Key &p_key) {
		const int position = find_exact(p_key);
		if (position >= 0) {
			pairs.remove_at(position);
		}
	}

	int find(const Key &p_key) const { return find_exact(p_key); }
	int size() const { return static_cast<int>(pairs.size()); }
	bool is_empty() const { return pairs.is_empty(); }

	const Pair *get_array() const { return pairs.ptr(); }
	Pair *get_array() { return pairs.ptrw(); }

	const Value &getv(int p_index) const { return pairs[p_index].value; }
	Value &getv(int p_index) { return pairs.write[p_index].value; }

	const Key &getk(int p_index) const { return pairs[p_index].key; }
	Key &getk(int p_index) { return pairs.write[p_index].key; }

	const Value &operator[](const Key &p_key) const {
		const int position = find_exact(p_key);
		CRASH_COND(position < 0);
		return pairs[position].value;
	}

	Value &operator[](const Key &p_key) {
		int position = find_exact(p_key);
		if (position < 0) {
			position = insert(p_key, Value());
		}
		return pairs.write[position].value;
	}
};

} // namespace godot

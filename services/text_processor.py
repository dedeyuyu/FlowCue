# -*- coding: utf-8 -*-
import re
import unicodedata

class TextProcessor:
    """Handles text cleaning and smart segmentation for Spanish / Nepali / multilingual content."""
    
    @staticmethod
    def remove_punctuation(text):
        """Removes all punctuation marks (English/Spanish, Chinese, and Nepali । / ॥) from text,
        while preserving Unicode combining marks (e.g. Devanagari vowel signs / matras)."""
        if not text:
            return ""
        out = []
        for c in text:
            if c == '_' or c.isspace():
                out.append(' ')
            elif re.match(r'\w', c) or unicodedata.category(c) in ('Mn', 'Mc', 'Me'):
                out.append(c)
            else:
                out.append(' ')
        return re.sub(r'\s+', ' ', "".join(out)).strip()

    @staticmethod
    def clean_text(text, language=None):
        """Cleans input text according to user rules:
        - Replaces newlines/CR with spaces (does not split on newlines)
        - Removes all emojis and symbols (like '👉', '📖', '✨')
        - Removes double quotes (", “, ”)
        - Converts emoji numbers (e.g. 3️⃣) to normal numbers
        """
        if not text:
            return ""
            
        # 0. Replace newlines and carriage returns with spaces
        text = text.replace('\r', ' ').replace('\n', ' ')
            
        # 1. Replace emoji numbers (like 3️⃣) with normal numbers
        # Match digit followed by optional variation selector U+FE0F and enclosing keycap U+20E3
        text = re.sub(r'(\d)\uFE0F?\u20E3', r'\1', text)
        
        # 2. Remove all other emojis and icons:
        # - Characters with code point > 0xFFFF (covers almost all modern emojis like 👉, 📖)
        # - Characters in the Miscellaneous Symbols block (0x2600-0x26FF) and Dingbats (0x2700-0x27BF)
        cleaned_chars = []
        for c in text:
            code = ord(c)
            if 0x2600 <= code <= 0x27BF or code > 0xFFFF:
                continue
            cleaned_chars.append(c)
        text = "".join(cleaned_chars)
        
        # 3. Remove quotes (double quotes, smart quotes)
        text = text.replace('"', '').replace('“', '').replace('”', '')
        
        # 4. Replace colons and parentheses (both English and Chinese) with a space
        for char in (':', '：', '(', ')', '（', '）'):
            text = text.replace(char, ' ')
            
        # 5. Remove spaces before punctuation (e.g. "13 ." -> "13.")
        if language == "ne":
            text = re.sub(r' +([।॥,?!;])', r'\1', text)
            text = re.sub(r'([।॥]+)(?=[^\s।॥])', r'\1 ', text)
        else:
            text = re.sub(r' +([.,?!;])', r'\1', text)
            
        # 6. Clean up spacing
        text = re.sub(r' +', ' ', text)
        
        return text.strip()

    @staticmethod
    def _extract_words_and_breaks(text, language=None):
        """Extracts clean words and natural punctuation break indicators from text.
        
        Returns:
            tuple: (words, break_types)
                - words: list of clean, punctuation-free word strings
                - break_types: list of int (same length as words), where:
                    2 = sentence break (., !, ?, ;, … or Nepali ।, ॥) right after this word
                    1 = clause/comma break (,, :, —, -) right after this word
                    0 = normal word boundary
        """
        if not text:
            return [], []
        is_nepali = (language == "ne")
        sent_endings = ('।', '॥', '!', '?', ';', '…') if is_nepali else ('.', '!', '?', ';', '…')
        raw_tokens = text.split()
        words = []
        break_types = []
        for token in raw_tokens:
            # Determine trailing punctuation type before stripping punctuation
            stripped_quotes = token.rstrip('\'"”’»)]}')
            b_type = 0
            if stripped_quotes.endswith(sent_endings):
                b_type = 2
            elif stripped_quotes.endswith((',', '，', ':', '—', '-')):
                b_type = 1

            clean_token = TextProcessor.remove_punctuation(token)
            if not clean_token:
                # If a standalone punctuation token appeared, attach break to previous word
                if b_type > 0 and break_types:
                    break_types[-1] = max(break_types[-1], b_type)
                continue

            sub_words = clean_token.split()
            for idx, sw in enumerate(sub_words):
                words.append(sw)
                if idx == len(sub_words) - 1:
                    break_types.append(b_type)
                else:
                    break_types.append(0)
        return words, break_types

    @staticmethod
    def _partition_words_balanced(words, k, min_chars=0, max_limit=None, break_types=None):
        """Partitions a list of clean words into exactly k contiguous segments
        such that EVERY segment has length >= min_chars (and <= max_limit if specified),
        while minimizing length variance around the balanced average (total_len / k).

        Returns:
            list[str] | None: List of k clean segment strings if a valid partition exists,
                              otherwise None.
        """
        m = len(words)
        if m == 0 or k <= 0 or k > m:
            return None

        if k == 1:
            joined = " ".join(words)
            length = len(joined)
            if length < min_chars:
                return None
            if max_limit is not None and length > max_limit and m > 1:
                return None
            return [joined]

        # Prefix character lengths of " ".join(words[:i])
        prefix = [0] * (m + 1)
        for i in range(1, m + 1):
            prefix[i] = prefix[i - 1] + len(words[i - 1]) + (1 if i > 1 else 0)

        def seg_len(a, b):
            return prefix[b] - prefix[a] - (1 if a > 0 else 0)

        total_len = prefix[m]
        target = total_len / k

        # dp[s][i] = (min_cost, prev_word_idx) for partitioning words[:i] into s segments
        INF = float("inf")
        dp = [[(INF, -1)] * (m + 1) for _ in range(k + 1)]
        dp[0][0] = (0.0, 0)

        for s in range(1, k + 1):
            # Each remaining segment needs at least 1 word
            max_end = m - (k - s)
            for a in range(s - 1, max_end):
                prev_cost = dp[s - 1][a][0]
                if prev_cost == INF:
                    continue

                # If last segment, b must be m; otherwise b ranges from a + 1 to max_end
                b_start = m if s == k else a + 1
                b_end = m if s == k else max_end

                for b in range(b_start, b_end + 1):
                    length = seg_len(a, b)
                    if length < min_chars:
                        continue
                    if max_limit is not None and length > max_limit:
                        # Allow a single oversized word only if b == a + 1
                        if b > a + 1:
                            break

                    # Squared deviation from ideal balanced length
                    cost = (length - target) ** 2

                    # Small preference for splitting at natural sentence/clause boundaries
                    # when they are already close to the balanced split point
                    if break_types is not None and b < m:
                        bt = break_types[b - 1]
                        if bt == 2:
                            cost -= 225.0  # ~15 chars tolerance for sentence boundary
                        elif bt == 1:
                            cost -= 100.0  # ~10 chars tolerance for comma boundary

                    total_cost = prev_cost + cost
                    if total_cost < dp[s][b][0]:
                        dp[s][b] = (total_cost, a)

        if dp[k][m][0] == INF:
            return None

        # Reconstruct the k segments
        result = []
        curr = m
        for s in range(k, 0, -1):
            prev = dp[s][curr][1]
            result.append(" ".join(words[prev:curr]))
            curr = prev
        result.reverse()
        return result

    @staticmethod
    def _split_long_chunk(chunk, max_len=170):
        """Splits a single chunk that is longer than max_len into sub-chunks.
        Tries to split by comma first, then by space (words).
        """
        if len(chunk) <= max_len:
            return [chunk]
            
        parts = chunk.split(', ')
        sub_chunks = []
        current = ""
        
        for i, p in enumerate(parts):
            # Append comma back if it's not the last element
            item = p + "," if i < len(parts) - 1 else p
            test = (current + " " + item).strip() if current else item
            
            if len(test) <= max_len:
                current = test
            else:
                if current:
                    sub_chunks.append(current)
                
                # If a single item is still > max_len, split by space (words)
                if len(item) > max_len:
                    words = item.split(' ')
                    word_current = ""
                    for w in words:
                        if not w:
                            continue
                        test_w = (word_current + " " + w).strip() if word_current else w
                        if len(test_w) <= max_len:
                            word_current = test_w
                        else:
                            if word_current:
                                sub_chunks.append(word_current)
                            word_current = w
                    current = word_current
                else:
                    current = item
                    
        if current:
            sub_chunks.append(current)
            
        return sub_chunks

    @staticmethod
    def segment_spanish_text(text, config_manager=None):
        """Segments cleaned Spanish text.
        Priority order:
        1. Forced split markers (e.g. '///', '|||', '$$') — hard block boundaries, never crossed.
        2. Minimum segment character count (min_segment_chars) — highest priority within each block.
        3. Maximum character limit (max_limit) & natural punctuation breaks.
        """
        if not text:
            return []
            
        max_limit = config_manager.get_max_chars() if config_manager else 170
        custom_marker = getattr(config_manager, "forced_split_marker", "///") if config_manager else "///"
        language = getattr(config_manager, "speech_language", "es") if config_manager else "es"
        
        # Build forced split markers pattern
        markers = [custom_marker, "///", "|||", "$$", "###", "[split]", "[断句]"]
        unique_markers = list(dict.fromkeys([m for m in markers if m]))
        pattern_str = '|'.join(re.escape(m) for m in unique_markers)
        
        # Pre-split text into isolated blocks by forced split markers
        forced_blocks = re.split(pattern_str, text)
        
        results = []
        for block in forced_blocks:
            cleaned_block = TextProcessor.clean_text(block, language=language)
            if not cleaned_block:
                continue
            # Process each forced block independently so no merging occurs across forced markers
            block_results = TextProcessor._segment_single_block(cleaned_block, max_limit, config_manager)
            results.extend(block_results)
            
        if results and config_manager:
            total_segs = len(results)
            for idx, seg in enumerate(results):
                is_edge = (idx == 0 or idx == total_segs - 1)
                seg["duration"] = config_manager.get_duration_for_length(seg["length"], is_edge=is_edge)

        return results

    @staticmethod
    def _segment_single_block(cleaned_text, max_limit, config_manager=None):
        """Segments a single forced block, giving min_segment_chars the highest priority."""
        import math
        min_chars = getattr(config_manager, "min_segment_chars", 0) if config_manager else 0
        language = getattr(config_manager, "speech_language", "es") if config_manager else "es"
        is_nepali = (language == "ne")
        sent_joiner = "। " if is_nepali else ". "
        # If user set min_chars higher than max_limit, min_chars takes precedence
        effective_max_limit = max(max_limit, min_chars) if min_chars > 0 else max_limit

        initial_chunks = []
        if is_nepali:
            # Split by Nepali sentence-ending punctuation (।, ॥, ?, !, ;)
            pattern = re.compile(r'([^।॥!?;]+[।॥!?;\s]*)')
        else:
            # Split by sentence-ending punctuation (., ?, !, ;)
            pattern = re.compile(r'([^.!?;]+[.!?;\s]*)')
        matches = pattern.findall(cleaned_text)
        
        for m in matches:
            trimmed = TextProcessor.remove_punctuation(m)
            if trimmed:
                initial_chunks.append(trimmed)

        # Stage 1: Enforce hard limit on raw chunks by pre-splitting anything > effective_max_limit
        raw_chunks = []
        for chunk in initial_chunks:
            if len(chunk) > effective_max_limit:
                raw_chunks.extend(TextProcessor._split_long_chunk(chunk, max_len=effective_max_limit))
            else:
                raw_chunks.append(chunk)

        # Stage 2: Greedy Merging up to effective_max_limit characters
        # Keep sent_joiner between merged sentence chunks so Stage 3 knows natural sentence boundaries
        segments = []
        current_segment = ""
        current_clean_len = 0
        
        for chunk in raw_chunks:
            chunk_clean = TextProcessor.remove_punctuation(chunk)
            if not chunk_clean:
                continue
            test_clean_len = (current_clean_len + 1 + len(chunk_clean)) if current_segment else len(chunk_clean)
            if test_clean_len <= effective_max_limit:
                current_segment = (current_segment + sent_joiner + chunk_clean) if current_segment else chunk_clean
                current_clean_len = test_clean_len
            else:
                if current_segment:
                    segments.append(current_segment)
                current_segment = chunk_clean
                current_clean_len = len(chunk_clean)

        if current_segment:
            segments.append(current_segment)
        
        # Stage 3: Strictly enforce minimum segment character count (Highest Priority after ///)
        if min_chars > 0 and len(segments) > 1:
            changed = True
            while changed and len(segments) > 1:
                changed = False
                for i in range(len(segments)):
                    seg_clean = TextProcessor.remove_punctuation(segments[i])
                    if len(seg_clean) >= min_chars:
                        continue

                    # Found a segment shorter than min_chars at index i!
                    # Strategy 1: Direct 1-segment merge with an adjacent neighbor if <= effective_max_limit.
                    # If both neighbors fit, merge with the shorter neighbor to keep lengths balanced.
                    merge_candidates = []
                    if i > 0:
                        comb_prev_raw = segments[i - 1] + sent_joiner + segments[i]
                        comb_prev_clean = TextProcessor.remove_punctuation(comb_prev_raw)
                        if len(comb_prev_clean) <= effective_max_limit:
                            merge_candidates.append((len(comb_prev_clean), i - 1, i + 1, comb_prev_raw))
                    if i + 1 < len(segments):
                        comb_next_raw = segments[i] + sent_joiner + segments[i + 1]
                        comb_next_clean = TextProcessor.remove_punctuation(comb_next_raw)
                        if len(comb_next_clean) <= effective_max_limit:
                            merge_candidates.append((len(comb_next_clean), i, i + 2, comb_next_raw))

                    if merge_candidates:
                        merge_candidates.sort(key=lambda x: x[0])
                        _, s_idx, e_idx, merged_raw = merge_candidates[0]
                        segments[s_idx:e_idx] = [merged_raw]
                        changed = True
                        break

                    # Strategy 2A: Segment-count-reducing redistribution (e.g., 3 segments -> 2 balanced segments)
                    # Try window_size = 3, 4 around i where k < window_size fits within [min_chars, effective_max_limit]
                    n = len(segments)
                    redistributed = False
                    for window_size in range(3, min(n, 5) + 1):
                        win_start_min = max(0, i - window_size + 1)
                        win_start_max = min(i, n - window_size)
                        for s_idx in range(win_start_min, win_start_max + 1):
                            e_idx = s_idx + window_size
                            comb_raw = sent_joiner.join(segments[s_idx:e_idx])
                            comb_clean = TextProcessor.remove_punctuation(comb_raw)
                            comb_len = len(comb_clean)
                            k_min = max(1, math.ceil(comb_len / effective_max_limit))
                            if k_min >= window_size:
                                continue
                            words, break_types = TextProcessor._extract_words_and_breaks(comb_raw, language=language)
                            for k in range(k_min, window_size):
                                new_segs = TextProcessor._partition_words_balanced(
                                    words, k, min_chars=min_chars,
                                    max_limit=effective_max_limit, break_types=break_types
                                )
                                if new_segs and all(len(TextProcessor.remove_punctuation(s)) >= min_chars for s in new_segs):
                                    segments[s_idx:e_idx] = new_segs
                                    redistributed = True
                                    break
                            if redistributed:
                                break
                        if redistributed:
                            break

                    if redistributed:
                        changed = True
                        break

                    # Strategy 2B: Balanced Multi-Segment Redistribution within [min_chars, effective_max_limit]
                    # Combine 2, 3, ..., up to all segments in the block and partition into k balanced segments
                    # (e.g. [169 chars, 13 chars] -> two balanced ~91-char segments!)
                    for window_size in range(2, n + 1):
                        win_start_min = max(0, i - window_size + 1)
                        win_start_max = min(i, n - window_size)
                        candidate_windows = []
                        for s_idx in range(win_start_min, win_start_max + 1):
                            e_idx = s_idx + window_size
                            comb_raw = sent_joiner.join(segments[s_idx:e_idx])
                            comb_clean = TextProcessor.remove_punctuation(comb_raw)
                            candidate_windows.append((len(comb_clean), s_idx, e_idx, comb_raw))

                        # Prefer combining with the longer neighbor first (e.g. 169 + 13 -> 88 + 94)
                        candidate_windows.sort(key=lambda x: -x[0])

                        for comb_len, s_idx, e_idx, comb_raw in candidate_windows:
                            words, break_types = TextProcessor._extract_words_and_breaks(comb_raw, language=language)
                            if not words:
                                continue
                            k_min = max(1, math.ceil(comb_len / effective_max_limit))
                            k_max = max(1, (comb_len + 1) // (min_chars + 1))
                            if k_min > k_max:
                                continue

                            for k in range(k_min, k_max + 1):
                                new_segs = TextProcessor._partition_words_balanced(
                                    words, k, min_chars=min_chars,
                                    max_limit=effective_max_limit, break_types=break_types
                                )
                                if new_segs and all(len(TextProcessor.remove_punctuation(s)) >= min_chars for s in new_segs):
                                    segments[s_idx:e_idx] = new_segs
                                    redistributed = True
                                    break
                            if redistributed:
                                break
                        if redistributed:
                            break

                    if redistributed:
                        changed = True
                        break

                    # Strategy 3: Ultimate Priority Fallback — min_segment_chars has HIGHER priority than max_limit!
                    full_raw = sent_joiner.join(segments)
                    full_words, full_breaks = TextProcessor._extract_words_and_breaks(full_raw, language=language)
                    full_len = len(" ".join(full_words))
                    k_feasible = max(1, (full_len + 1) // (min_chars + 1))
                    for k in range(k_feasible, 0, -1):
                        new_segs = TextProcessor._partition_words_balanced(
                            full_words, k, min_chars=min_chars,
                            max_limit=None, break_types=full_breaks
                        )
                        if new_segs and all(len(TextProcessor.remove_punctuation(s)) >= min_chars for s in new_segs):
                            segments[:] = new_segs
                            redistributed = True
                            break

                    if redistributed:
                        changed = True
                        break

                    # Final unconditional merge (when entire block has fewer than min_chars characters)
                    if i > 0 and (i + 1 >= len(segments) or len(segments[i - 1]) <= len(segments[i + 1])):
                        segments[i - 1] = segments[i - 1] + sent_joiner + segments[i]
                        segments.pop(i)
                    elif i + 1 < len(segments):
                        segments[i] = segments[i] + sent_joiner + segments[i + 1]
                        segments.pop(i + 1)
                    changed = True
                    break

        # Assign durations
        block_results = []
        for seg in segments:
            seg_text = TextProcessor.remove_punctuation(seg)
            if not seg_text:
                continue
            length = len(seg_text)
            
            if config_manager:
                duration_val = config_manager.get_duration_for_length(length)
            else:
                if length <= 40:
                    duration_val = 4
                elif length <= 90:
                    duration_val = 6
                elif length <= 130:
                    duration_val = 8
                else:
                    duration_val = 10
                
            block_results.append({
                "text": seg_text,
                "length": length,
                "duration": duration_val
            })
            
        return block_results


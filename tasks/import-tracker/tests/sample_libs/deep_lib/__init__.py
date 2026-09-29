"""Library that depends on mylib (another sample lib on sys.path).
Used to test full_depth: without full_depth, only 'mylib' shows as a dep.
With full_depth, tracker follows into mylib and finds yaml/alog."""

import mylib

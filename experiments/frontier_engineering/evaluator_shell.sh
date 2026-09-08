#!/bin/sh
# UnifiedTask uses -lc; host login profiles must not change its evaluator cwd.
exec bash --noprofile --norc "$@"

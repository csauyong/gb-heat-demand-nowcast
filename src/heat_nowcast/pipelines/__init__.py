"""End-to-end assembly steps.

Pipelines compose loaders, features, models and evaluation into a single
reproducible run. They live in ``src/`` rather than in a notebook because
`CLAUDE.md` §7 puts analysis logic under test and under version control;
notebooks render results, they do not compute them.
"""

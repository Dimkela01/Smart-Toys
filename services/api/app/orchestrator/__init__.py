"""The turn pipeline: prompt assembly, sentence streaming, and the turn itself.

One child utterance in, ordered sentences of audio out (ARCHITECTURE.md §6). Safety
layers L1 and L4 plug in here in M3; the activity engine in M4.
"""

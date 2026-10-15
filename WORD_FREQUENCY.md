# Word frequency data

`wordfreq-en-25000-log.json` is an English word frequency export from Alex
Parrish's [`wordfreq-en-25000` repository](https://github.com/aparrish/wordfreq-en-25000).
The exported frequency data comes from the [`wordfreq` project](https://pypi.org/project/wordfreq/),
authored by Robyn Speer and based on multiple text sources.

The export contains 25,000 words with the natural logarithm of each word's
frequency fraction. This app converts a stored value `x` to a Zipf score with
`9 + x / ln(10)`, matching the Zipf scale described by `wordfreq`: base-10 log
frequency per billion words. The JSON is used locally by the review page and
is not fetched from a third-party service at runtime.

The exported data is provided under the
[Creative Commons Attribution-ShareAlike 4.0 International license](https://creativecommons.org/licenses/by-sa/4.0/).
Attribution: Alex Parrish, *wordfreq-en-25000*, exporting English frequencies
from Robyn Speer's *wordfreq*. This project includes the exported JSON and
converts the log frequency values to Zipf scores for display. The accompanying
export script is public domain according to its repository.

This is general English usage frequency. It does not measure how familiar a
word is to Scrabble players, and a word missing from the 25,000-word export is
shown as having no estimate rather than as rare.

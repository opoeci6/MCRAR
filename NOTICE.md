# Notices and licences

**MCRAR is a non-commercial project.** The source code is MIT-licensed, but parts of what the
app uses are not: some trained tag models and one optional embedding model may only be used
non-commercially. So MCRAR as a whole must not be used commercially, for example run as a paid
service. Nothing here is legal advice.

## Source code

The code in this repository is under the MIT licence in [`LICENSE`](LICENSE), except for the
files listed below.

## Trained tag models (`models/heads/`)

Small numpy files (`.npz`) fitted on top of CLAP embeddings, with their metadata in
[`models/registry.json`](models/registry.json). Each one follows the licence of its training
data; the registry records it per file as `data_license` and `commercial_ok`.

| Files | Trained on | Terms |
|---|---|---|
| `genre-*` | FMA (`fma_medium`): metadata CC BY 4.0, audio under per-track Creative Commons licences | Recorded as `commercial_ok: true`; attribute FMA |
| `moodtheme-logreg@…`, `moodtheme-mlp@…`, `moodtheme-zeroshot-calibrated@…` | MTG-Jamendo mood/theme annotations, CC BY-NC-SA 4.0 | **Non-commercial, share-alike:** these files are shared under CC BY-NC-SA 4.0 |
| `moodtheme-zeroshot-unsupervised@…` | No labels (text prompts, fitted on FMA audio embeddings) | Recorded as `commercial_ok: true` |
| `valence-*`, `arousal-*` | DEAM, CC BY-NC (version not stated in the DEAM manual) | **Non-commercial** |
| `scene-*` | Text prompts, the catalog's own CLAP vectors, and hand labels by the project team | No third-party data licence |

The models the app uses by default include the non-commercial `moodtheme-mlp`, `valence-mlp`
and `arousal-mlp` (the `selected` map in `models/registry.json`).

## Embedding models (downloaded on first use, not part of this repository)

| Model | Hugging Face id | Licence |
|---|---|---|
| CLAP (the default) | `laion/larger_clap_music_and_speech` | Apache-2.0 |
| GLAP (optional) | `mispeech/GLAP` | Apache-2.0 |
| MuQ-MuLan (optional) | `OpenMuQ/MuQ-MuLan-large` | **CC BY-NC 4.0, non-commercial** |

## Datasets (used for training and evaluation; not redistributed)

- **FMA:** M. Defferrard, K. Benzi, P. Vandergheynst, X. Bresson. *FMA: A Dataset for Music
  Analysis.* ISMIR 2017.
- **MTG-Jamendo:** D. Bogdanov, M. Won, P. Tovstogan, A. Porter, X. Serra. *The MTG-Jamendo
  Dataset for Automatic Music Tagging.* Machine Learning for Music Discovery Workshop, ICML 2019.
- **DEAM:** A. Aljanaki, Y.-H. Yang, M. Soleymani. *Developing a benchmark for emotional
  analysis of music.* PLOS ONE, 2017.
- **Song Describer Dataset** (the embedding bake-off): I. Manco et al. *The Song Describer
  Dataset: a Corpus of Audio Captions for Music-and-Language Evaluation.* 2023.

## Music

MCRAR doesn't ship or re-host any music. Tracks are streamed from their source or played from
your own disk, and each keeps its own licence:

- **Jamendo** (through the Jamendo API with your own client id): Creative Commons licences per
  track.
- **Freesound** (through the Freesound API with your own key, which Freesound grants for
  non-commercial use): CC0, CC BY and, if you allow it, CC BY-NC.
- **Your own folders and asset packs:** the licence you declare.

The green, amber and red badges summarise a track's licence for use in a game. They are
guidance, not legal advice: read the linked licence before you use a track.

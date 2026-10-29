# Labelling game scenes (M9)

> **M9 is done (2026-10-28):** 269 labelled tracks from two labellers. The trained hybrid head
> won narrowly and is selected; the labellers agreed little (mean Cohen's kappa 0.24). Results
> are in `docs/model_card.md`, "Game scenes", and the decisions in STATUS §3.13. The workflow
> below still applies to new labels.

The scene tags (combat, boss, menu, ...) come from text prompts, with no data to check them
against. Hand labels fix that: they tell us which of the zero-shot variants is better, and
they can train a small head on top. This page says what a label means and how the two of us
(the owner and a collaborator) split the work. Run commands through the env wrapper, for example
`scripts/with-env.sh uv run --directory backend mcrar scenes pool`.

## What a label means

Listen to the track (the first minute or so is enough) and tick **every scene it could
plausibly be the music for in a game**, then pick how intense it feels.

| Scene | The music could play during |
|---|---|
| `combat` | Fighting ordinary enemies, action sequences |
| `boss` | A boss fight, a final battle |
| `exploration` | Travelling through an open world or an adventure |
| `menu` | The main menu or title screen |
| `town` | A peaceful town, a village, a shop |
| `puzzle` | Solving puzzles, calm thinking levels |
| `stealth` | Sneaking, tense infiltration |
| `horror` | Scary or haunted places |
| `victory` | A win, a level-complete fanfare |
| `defeat` | Game over, losing |
| `credits` | The end credits |
| `cutscene` | An emotional story moment or farewell |
| `chase` | Fleeing or being chased, frantic escapes |
| `ambient` | Quiet background atmosphere, building, farming |

- **Intensity** is `low` (calm, background), `mid` or `high` (loud, driving). It is optional.
- **None fit** is a real answer: save the label with no scene ticked. The model should learn
  that such tracks match nothing.
- **Skip** is for a track you cannot judge (broken audio, no time). A skipped track is not
  asked again, and it counts as neither a positive nor a negative.
- Judge the sound, not the title. Do not look the track up first.

## The pool

`mcrar scenes pool` picks the tracks to label (about 270 on a catalog of a few thousand):

- the top 10 tracks per scene of **every** zero-shot entry (plain and centered), so the
  variants get compared on the tracks where they disagree;
- 100 random other tracks, so there are tracks no model picked;
- all shuffled into one order, so no stretch of the list is all one scene.

Each track belongs to part **A**, part **B**, or **both** (30 tracks, spread through the list,
that both of us label so we can measure how much we agree). The owner labels A plus both, the
collaborator B plus both. The pool is chosen from the stored zero-shot scores and a seed, so it
is reproducible. It needs `mcrar scenes build`, not `mcrar tag`. It refuses to replace an existing
pool unless you pass `--force`; labels belong to tracks, so they survive a new pool.

The labelling page never shows why a track is in the pool, so that does not influence you.

## The owner

```bash
mcrar scenes build               # two zero-shot variants from the catalog's CLAP vectors
mcrar tag --label-sets scene     # stores their scores (search uses them)
mcrar scenes pool                # chooses the pool
mcrar scenes export-pack pack.json   # send this file to the collaborator
mcrar serve                      # then open the Labelling tab, pick part A and your name
```

Label until the page says part A is done (Back and the list let you revisit a track). Then:

```bash
mcrar scenes import-labels their-labels.json    # the collaborator's file
mcrar scenes eval                # how every entry scores on the labels; also written to data/
mcrar scenes train               # fits the optional head and selects the best entry
mcrar tag --label-sets scene     # only if train says the selection changed
```

`eval` prints precision@10 and average precision per scene for each entry on the labelled
tracks (the head is cross-validated), the catalog top-10 per scene with how many of those tracks
are labelled, Spearman's rho of the DSP energy and the arousal head against your intensity, and
Cohen's kappa between the two of you on the shared tracks. Scenes with fewer than 5 positives
say "too few". `train` records the cross-validated mean P@10 of every entry in the registry and
selects the best; on a tie the simpler entry wins (zero-shot before the head, then the lower
centering). The model card gets a "Game scenes" section from the newest result.

## The collaborator

A step-by-step checklist for the collaborator and their agent is in
[`docs/handover/M9-labelling.md`](handover/M9-labelling.md).

1. Pull the branch and get your own Jamendo client id (free, from
   <https://devportal.jamendo.com>); store it with `mcrar secrets set jamendo_client_id`. The pack
   does not contain the owner's key, and no audio is downloaded: labelling streams the tracks
   with your key.
2. Import the pack the owner sent. Tracks you lack are fetched from Jamendo by id (metadata
   only, no analysis or embedding); anything that cannot be fetched is listed and skipped:

   ```bash
   mcrar scenes import-pack pack.json
   ```

   Use `--no-fetch` to map only the tracks you already have, and `--force` to replace an
   existing pool.
3. Run `mcrar serve`, open the **Labelling** tab, pick **part B** and type your name (the name
   is how your labels are told apart from the owner's; use the same one every time).
4. When part B is done, send the owner your labels:

   ```bash
   mcrar scenes export-labels my-labels.json --labeller "Your Name"
   ```

   The Labelling tab can also download the same file.

Tracks are matched across catalogs by source and id, never by local numbers. If a labels file
holds a label that the other catalog already has from the same person, the newer one is kept.
`mcrar scenes import-labels --as NAME` stores everything in a file under another name.

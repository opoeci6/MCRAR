/**
 * A tag score at or above this is shown as "strong" in a result row. The score is standardised
 * against the catalog (`sigmoid(1.7 z)`, 0.5 = catalog average), and a row shows each track's
 * five highest, so nearly all chips are above 0.9. Measured on the owner's catalog (8 typical
 * searches, 800 chips, 2026-10-27): 98 % of chips reach 0.9, 54 % reach 0.98 and 29 % reach
 * 0.995 (about z >= 3.1). The word only means something when it is rare.
 */
export const STRONG_TAG_SCORE = 0.995

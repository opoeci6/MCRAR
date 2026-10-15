import type { Risk } from '../api/types'
import { cx } from '../lib/cx'
import { strings } from '../strings'
import { AlertIcon, CheckIcon, CloseIcon, QuestionIcon } from './icons'
import { Popover } from './Popover'
import type { PopoverPlacement } from './Popover'
import styles from './LicenseBadge.module.css'

export interface LicenseBadgeProps {
  risk: Risk
  /** The licence code, for example "CC BY 4.0". */
  code: string | null | undefined
  /** The credit line to give the artist. */
  attribution?: string | null
  licenseUrl?: string | null
  commercialLicenseUrl?: string | null
  placement?: PopoverPlacement
  className?: string
}

const ICONS = {
  green: CheckIcon,
  amber: AlertIcon,
  red: CloseIcon,
  unknown: QuestionIcon,
} as const

function BadgeFace({ risk, code }: Pick<LicenseBadgeProps, 'risk' | 'code'>) {
  const Icon = ICONS[risk]
  return (
    <>
      <Icon width={12} height={12} />
      <span className="sr-only">{`${strings.license.label}: `}</span>
      <span className={styles.risk}>{strings.license.risk[risk]}</span>
      <span className={styles.code}>{code || strings.license.noCode}</span>
    </>
  )
}

/**
 * The licence of a track: the risk as a word, an icon and a colour (never colour alone), and the
 * licence code. When there is a credit line or a link, the badge is a button that opens them.
 */
export function LicenseBadge({
  risk,
  code,
  attribution,
  licenseUrl,
  commercialLicenseUrl,
  placement,
  className,
}: LicenseBadgeProps) {
  const known: Risk = risk in ICONS ? risk : 'unknown'
  const hasDetails = Boolean(attribution || licenseUrl || commercialLicenseUrl)
  const tone = cx(styles.badge, styles[known], className)

  if (!hasDetails) {
    return (
      <span className={tone} title={strings.license.riskLong[known]}>
        <BadgeFace risk={known} code={code} />
      </span>
    )
  }

  return (
    <Popover
      label={strings.license.details}
      placement={placement}
      trigger={(props) => (
        <button type="button" className={cx(tone, styles.button)} {...props}>
          <BadgeFace risk={known} code={code} />
        </button>
      )}
    >
      <div className={styles.details}>
        <p className={styles.explain}>{strings.license.riskLong[known]}</p>
        {attribution ? (
          <div>
            <div className={styles.heading}>{strings.license.attribution}</div>
            <p className={styles.credit}>{attribution}</p>
          </div>
        ) : null}
        {licenseUrl || commercialLicenseUrl ? (
          <ul className={styles.links}>
            {licenseUrl ? (
              <li>
                <a href={licenseUrl} target="_blank" rel="noreferrer noopener">
                  {strings.license.licenseLink}
                  <span className="sr-only"> {strings.common.opensInNewTab}</span>
                </a>
              </li>
            ) : null}
            {commercialLicenseUrl ? (
              <li>
                <a href={commercialLicenseUrl} target="_blank" rel="noreferrer noopener">
                  {strings.license.commercialLink}
                  <span className="sr-only"> {strings.common.opensInNewTab}</span>
                </a>
              </li>
            ) : null}
          </ul>
        ) : null}
      </div>
    </Popover>
  )
}

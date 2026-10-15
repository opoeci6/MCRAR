import type { SVGProps } from 'react'

/** Small inline icons (16 px, `currentColor`). Decorative: always pair them with text or a label. */
function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  )
}

export const PlayIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p} fill="currentColor" stroke="none">
    <path d="M4.5 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L5.4 2.3a.6.6 0 0 0-.9.5Z" />
  </Icon>
)

export const PauseIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p} fill="currentColor" stroke="none">
    <rect x="3.5" y="2.5" width="3.2" height="11" rx="1" />
    <rect x="9.3" y="2.5" width="3.2" height="11" rx="1" />
  </Icon>
)

export const CloseIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
  </Icon>
)

export const PlusIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M8 3v10M3 8h10" />
  </Icon>
)

export const CheckIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 8.5l3.2 3.2L13 4.8" />
  </Icon>
)

export const ChevronDownIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 6l4 4 4-4" />
  </Icon>
)

export const AlertIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M8 3v6M8 12v.5" />
  </Icon>
)

export const InfoIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M8 7.2v4.5M8 4.4v.2" />
  </Icon>
)

export const VolumeIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M2.5 6v4h2.6L9 12.8V3.2L5.1 6H2.5Z" />
    <path d="M11.5 5.5a3.6 3.6 0 0 1 0 5" />
  </Icon>
)

export const MusicIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 11.5V3.5l7-1.5v8" />
    <circle cx="4.5" cy="11.5" r="1.7" />
    <circle cx="11.5" cy="10" r="1.7" />
  </Icon>
)

export const QuestionIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M5.8 6.2a2.3 2.3 0 1 1 3.4 2c-.8.4-1.2.9-1.2 1.8M8 12.4v.2" />
  </Icon>
)

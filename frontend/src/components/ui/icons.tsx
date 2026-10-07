// A few hand-drawn line icons, used only where they carry meaning next to text.

type IconProps = { className?: string; title?: string };

function Svg({ className, title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8.5l3.2 3L13 4.5" />
  </Svg>
);

export const AlertIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 1.75l6.5 12H1.5z" />
    <path d="M8 6.5v3.25M8 11.9v.1" />
  </Svg>
);

export const CrossIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 4l8 8M12 4l-8 8" />
  </Svg>
);

export const InfoIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6.25" />
    <path d="M8 7.25v4M8 4.75v.1" />
  </Svg>
);

export const ClockIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6.25" />
    <path d="M8 4.5V8l2.25 1.5" />
  </Svg>
);

export const DotIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="3" fill="currentColor" stroke="none" />
  </Svg>
);

export const MinusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 8h8" />
  </Svg>
);

export const LoopIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12.5 6.5A4.75 4.75 0 0 0 3.6 5.2M3.5 9.5a4.75 4.75 0 0 0 8.9 1.3" />
    <path d="M3.25 2.5v2.75H6M12.75 13.5v-2.75H10" />
  </Svg>
);

export const ArrowIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 8h11M9.5 4l4 4-4 4" />
  </Svg>
);

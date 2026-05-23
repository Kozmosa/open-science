import { useEffect, useRef } from 'react';

interface Props {
  onVisible: () => void;
  loading: boolean;
}

export default function LoadMoreSentinel({ onVisible, loading }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) onVisible();
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onVisible]);

  return (
    <div ref={ref} className="h-8 flex items-center justify-center">
      {loading && (
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--apple-blue)]" />
      )}
    </div>
  );
}

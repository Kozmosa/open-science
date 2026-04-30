import { forwardRef, type TextareaHTMLAttributes } from 'react';

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: string;
}

const Textarea = forwardRef<HTMLTextAreaElement, Props>(function Textarea(
  { error, className = '', ...rest },
  ref
) {
  const errorClasses = error
    ? 'border-[#ff3b30] focus:border-[#ff3b30] focus:ring-[#ff3b30]/15'
    : 'border-[var(--border)] focus:border-[var(--apple-blue)] focus:ring-[var(--apple-blue)]/15';
  return (
    <textarea
      ref={ref}
      className={[
        'w-full rounded-lg bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition',
        errorClasses,
        'focus:ring-2',
        className,
      ].join(' ')}
      {...rest}
    />
  );
});

export default Textarea;

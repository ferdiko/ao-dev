import { useEffect, useState } from "react";
import { Check, Copy, Mail, X } from "lucide-react";

const DISCORD_INVITE_URL = "https://discord.gg/fjsNSa6TAh";
const SUPPORT_EMAIL = "support@sovara-labs.com";
const COPY_FEEDBACK_TIMEOUT_MS = 1500;

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function DiscordIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      fill="currentColor"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <path d="M20.317 4.369a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.211.375-.444.864-.608 1.249a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.249.077.077 0 0 0-.079-.037 19.736 19.736 0 0 0-4.885 1.515.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.056 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.11 14.11 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.095.252-.194.372-.294a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.009c.121.1.247.2.373.295a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.04.107c.36.698.771 1.364 1.225 1.994a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.055c.5-5.177-.838-9.674-3.548-13.66a.061.061 0 0 0-.031-.028Zm-11.64 10.817c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.211 0 2.166 1.095 2.157 2.419 0 1.334-.955 2.419-2.157 2.419Zm6.646 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.211 0 2.166 1.095 2.157 2.419 0 1.334-.946 2.419-2.157 2.419Z" />
    </svg>
  );
}

export function SupportModal({ onClose }: { onClose: () => void }) {
  const [emailCopied, setEmailCopied] = useState(false);

  useEffect(() => {
    if (!emailCopied) return;
    const timeoutId = window.setTimeout(() => setEmailCopied(false), COPY_FEEDBACK_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [emailCopied]);

  const handleCopyEmail = async () => {
    await copyText(SUPPORT_EMAIL);
    setEmailCopied(true);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal support-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Support</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <p className="support-modal-intro">
          Questions, feedback, or a blocker in the workflow? Reach out directly and we will help.
        </p>

        <div className="support-contact-list">
          <div className="support-contact-card support-contact-card-with-action">
            <a className="support-contact-link" href={`mailto:${SUPPORT_EMAIL}`}>
              <span className="support-contact-icon support-contact-icon-email">
                <Mail size={18} />
              </span>
              <span className="support-contact-copy">
                <span className="support-contact-title">Email</span>
                <span className="support-contact-detail">{SUPPORT_EMAIL}</span>
              </span>
            </a>
            <button
              aria-label={emailCopied ? "Email copied" : "Copy email"}
              className="support-contact-action"
              onClick={handleCopyEmail}
              title={emailCopied ? "Copied" : "Copy email"}
              type="button"
            >
              {emailCopied ? <Check size={16} /> : <Copy size={16} />}
            </button>
          </div>

          <a
            className="support-contact-card"
            href={DISCORD_INVITE_URL}
            rel="noreferrer"
            target="_blank"
          >
            <span className="support-contact-icon support-contact-icon-discord">
              <DiscordIcon size={18} />
            </span>
            <span className="support-contact-copy">
              <span className="support-contact-title">Discord server</span>
              <span className="support-contact-detail">Join the community and talk to us there</span>
            </span>
          </a>
        </div>

        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

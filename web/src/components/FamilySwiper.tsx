"use client";

export default function FamilySwiper() {
  return (
    <div className="family-banner-container" aria-label="Agent Family Portrait">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/agent-family-banner.png"
        alt="House of Google AI Butler Family portrait"
        className="family-banner-image"
      />

      <style jsx>{`
        .family-banner-container {
          width: 100%;
          border: 1px solid var(--border);
          border-radius: 14px;
          background: #06090f;
          overflow: hidden;
          box-shadow: var(--shadow);
        }

        .family-banner-image {
          display: block;
          width: 100%;
          height: auto;
          max-height: 350px;
          object-fit: cover;
          object-position: center top;
        }

        @media (max-width: 900px) {
          .family-banner-image {
            max-height: 280px;
          }
        }

        @media (max-width: 600px) {
          .family-banner-image {
            max-height: 220px;
          }
        }
      `}</style>
    </div>
  );
}

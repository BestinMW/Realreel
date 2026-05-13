import "./globals.css";

export const metadata = {
  title: "RealReel",
  description: "Preview a video from a URL.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

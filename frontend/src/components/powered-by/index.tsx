import Typography from "../typography";

interface BrandingWindow extends Window {
  powered_by_text?: string;
  powered_by_url?: string;
}

const PoweredBy = () => {
  // Branding text + URL are injected by the schedule template from
  // Appointment Settings.powered_by_text / .powered_by_url. An empty
  // text hides the footer entirely. An empty URL renders plain text.
  const w = window as unknown as BrandingWindow;
  const text = (w.powered_by_text ?? "").trim();
  const url = (w.powered_by_url ?? "").trim();

  if (!text) {
    return null;
  }

  const brandLink = url ? (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="font-semibold hover:underline text-blue-400"
    >
      {text}
    </a>
  ) : (
    <span className="font-semibold">{text}</span>
  );

  return (
    <>
      <div className="flexitems-center w-full justify-center shrink-0">
        <Typography
          variant="h5"
          className="flex items-center py-5 max-md:pb-20 max-lg:py-2 justify-center gap-1"
        >
          <Typography variant="p"> Powered by</Typography>
          <Typography variant="p">{brandLink}</Typography>
        </Typography>
      </div>
    </>
  );
};

export default PoweredBy;

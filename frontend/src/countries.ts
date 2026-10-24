export function countryFlag(code: string) {
  return code
    .toUpperCase()
    .replace(/[A-Z]/g, (letter) =>
      String.fromCodePoint(127397 + letter.charCodeAt(0)),
    );
}

const countryNames: Record<string, string> = {
  US: "United States",
  NL: "Netherlands",
  DE: "Germany",
  SG: "Singapore",
  JP: "Japan",
  GB: "United Kingdom",
  CA: "Canada",
  AU: "Australia",
  AM: "Armenia",
  LK: "Sri Lanka",
};

export function countryName(code: string) {
  if (code === "UK") return "United Kingdom";
  try {
    return (
      new Intl.DisplayNames(["en"], { type: "region" }).of(code) ||
      countryNames[code] ||
      code
    );
  } catch {
    return countryNames[code] || code;
  }
}

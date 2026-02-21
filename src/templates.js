const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

const DAYS = [
  'Sunday', 'Monday', 'Tuesday', 'Wednesday',
  'Thursday', 'Friday', 'Saturday',
];

export function renderTemplate(text) {
  const now = new Date();

  let result = text;

  // {{date}} → "16 Feb 2026"
  result = result.replace(/\{\{date\}\}/g, () => {
    return `${now.getDate()} ${MONTHS[now.getMonth()]} ${now.getFullYear()}`;
  });

  // {{day}} → "Monday"
  result = result.replace(/\{\{day\}\}/g, () => {
    return DAYS[now.getDay()];
  });

  // {{random:opt1|opt2|opt3}} → picks one randomly
  result = result.replace(/\{\{random:([^}]+)\}\}/g, (_, options) => {
    const choices = options.split('|').map((s) => s.trim());
    return choices[Math.floor(Math.random() * choices.length)];
  });

  return result;
}

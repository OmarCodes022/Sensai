// Before printing, expand what is collapsed (tool cards, details) and restore it afterwards.
let opened = [];

export function installPrint() {
  addEventListener('beforeprint', () => {
    opened = [];
    for (const el of document.querySelectorAll('.toolcard__body[hidden]')) { el.hidden = false; opened.push(() => { el.hidden = true; }); }
    for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; opened.push(() => { d.open = false; }); }
  });
  addEventListener('afterprint', () => { opened.forEach((f) => f()); opened = []; });
}

(() => {
  const button = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.site-nav');
  if (button && nav) {
    button.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  const slides = [...document.querySelectorAll('.hero-slide')];
  const dots = [...document.querySelectorAll('.hero-dot')];
  if (slides.length > 1) {
    let active = 0;
    const show = (i) => {
      slides.forEach((s, n) => s.classList.toggle('active', n === i));
      dots.forEach((d, n) => d.classList.toggle('active', n === i));
      active = i;
    };
    dots.forEach((d, i) => d.addEventListener('click', () => show(i)));
    setInterval(() => show((active + 1) % slides.length), 5000);
  }
})();

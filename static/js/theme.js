const themeToggle = document.querySelector('#theme-toggle');
const savedTheme = localStorage.getItem('theme');
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

function setTheme(isDark) {
    document.documentElement.classList.toggle('dark-mode', isDark);
    themeToggle.setAttribute('aria-pressed', String(isDark));
    themeToggle.setAttribute(
        'aria-label',
        isDark ? 'Aktiver lys modus' : 'Aktiver mørk modus'
    );
    themeToggle.querySelector('span').textContent = isDark ? '☀️' : '🌙';
    themeToggle.querySelector('.theme-toggle-text').textContent = isDark
        ? 'Lys modus'
        : 'Mørk modus';
}

setTheme(savedTheme ? savedTheme === 'dark' : prefersDark);

themeToggle.addEventListener('click', () => {
    const isDark = !document.documentElement.classList.contains('dark-mode');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    setTheme(isDark);
});

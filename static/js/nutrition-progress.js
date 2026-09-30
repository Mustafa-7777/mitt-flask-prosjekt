const periodButtons = document.querySelectorAll("[data-progress-period-button]");
const periodPanels = document.querySelectorAll("[data-progress-period]");
const periodCaptions = document.querySelectorAll("[data-progress-period-caption]");

periodButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const selectedPeriod = button.dataset.progressPeriodButton;

        periodButtons.forEach((periodButton) => {
            periodButton.setAttribute(
                "aria-pressed",
                String(periodButton === button),
            );
        });
        periodPanels.forEach((panel) => {
            panel.hidden = panel.dataset.progressPeriod !== selectedPeriod;
        });
        periodCaptions.forEach((caption) => {
            caption.hidden = caption.dataset.progressPeriodCaption !== selectedPeriod;
        });
    });
});

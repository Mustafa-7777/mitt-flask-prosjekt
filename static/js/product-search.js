const searchForm = document.getElementById("product-search-form");

if (searchForm) {
    const queryInput = document.getElementById("product-search-query");
    const searchButton = searchForm.querySelector("button[type='submit']");
    const status = document.getElementById("product-search-status");
    const resultsList = document.getElementById("product-search-results");
    const nutrientNames = {
        kcal: "Kalorier",
        protein: "Protein",
        carbs: "Karbohydrater",
        fat: "Fett",
        saturated_fat: "Mettet fett",
        fiber: "Fiber",
        sugar: "Sukker",
        salt: "Salt",
    };

    searchForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = queryInput.value.trim();
        if (query.length < 2) {
            status.textContent = "Skriv minst to tegn for å søke.";
            return;
        }

        resultsList.replaceChildren();
        status.textContent = "Søker etter produkter …";
        searchButton.disabled = true;

        try {
            const response = await fetch(
                `/matlogg/sok-produkter?q=${encodeURIComponent(query)}`,
                { headers: { Accept: "application/json" } },
            );
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Produktsøket mislyktes.");
            }

            if (!data.products.length) {
                status.textContent = "Fant ingen produkter. Prøv et annet søkeord.";
                return;
            }

            status.textContent = `Fant ${data.products.length} produkter. Velg ett for å fylle ut skjemaet.`;
            data.products.forEach((product) => {
                const item = document.createElement("li");
                const chooseButton = document.createElement("button");
                chooseButton.type = "button";
                chooseButton.className = "nutrition-search-result";

                const productName = document.createElement("strong");
                productName.textContent = product.name;
                chooseButton.append(productName);

                const details = [product.brands, product.quantity].filter(Boolean);
                if (details.length) {
                    const productDetails = document.createElement("small");
                    productDetails.textContent = details.join(" · ");
                    chooseButton.append(productDetails);
                }

                chooseButton.addEventListener("click", () => {
                    document.getElementById("name").value = product.name;
                    const description = [
                        product.brands ? `Merke: ${product.brands}` : "",
                        product.quantity ? `Pakningsstørrelse: ${product.quantity}` : "",
                        `Data fra Open Food Facts: ${product.url}`,
                    ].filter(Boolean);
                    document.getElementById("description").value = description.join("\n");

                    const missing = [];
                    Object.entries(nutrientNames).forEach(([key, label]) => {
                        const input = document.getElementById(key);
                        const value = product.nutrients[key];
                        input.value = value === null ? "" : value;
                        if (value === null) {
                            missing.push(label);
                        }
                    });

                    status.textContent = missing.length
                        ? `Skjemaet er fylt ut. Mangler ${missing.join(", ")} — fyll inn disse fra pakken før du lagrer.`
                        : "Skjemaet er fylt ut. Kontroller verdiene mot pakken før du lagrer.";
                    document.getElementById("name").scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                    });
                });
                item.append(chooseButton);
                resultsList.append(item);
            });
        } catch (error) {
            status.textContent = error.message || "Kunne ikke søke etter produkter.";
        } finally {
            searchButton.disabled = false;
        }
    });
}

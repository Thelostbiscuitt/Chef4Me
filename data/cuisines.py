from models.ingredient import Category

CATEGORIES = {
    Category.PROTEIN.value: "🥩 Protein",
    Category.VEGETABLE.value: "🥬 Vegetable",
    Category.GRAIN.value: "🌾 Grain",
    Category.DAIRY.value: "🧀 Dairy",
    Category.SPICE.value: "🌶️ Spice",
    Category.SAUCE.value: "🫙 Sauce",
    Category.OIL.value: "🫒 Oil",
    Category.FRUIT.value: "🍎 Fruit",
    Category.BEVERAGE.value: "🥤 Beverage",
    Category.OTHER.value: "📦 Other",
}

CATEGORY_LIST = list(CATEGORIES.keys())

CUISINE_EMOJIS = {
    "thai": "🇹🇭", "chinese": "🇨🇳", "japanese": "🇯🇵", "korean": "🇰🇷",
    "indian": "🇮🇳", "italian": "🇮🇹", "mexican": "🇲🇽", "french": "🇫🇷",
    "spanish": "🇪🇸", "greek": "🇬🇷", "turkish": "🇹🇷", "moroccan": "🇲🇦",
    "ethiopian": "🇪🇹", "nigerian": "🇳🇬", "ghanaian": "🇬🇭", "kenyan": "🇰🇪",
    "vietnamese": "🇻🇳", "filipino": "🇵🇭", "indonesian": "🇮🇩", "malaysian": "🇲🇾",
    "brazilian": "🇧🇷", "peruvian": "🇵🇪", "colombian": "🇨🇴", "argentine": "🇦🇷",
    "jamaican": "🇯🇲", "cuban": "🇨🇺", "lebanese": "🇱🇧", "iranian": "🇮🇷",
    "israeli": "🇮🇱", "american": "🇺🇸", "british": "🇬🇧", "german": "🇩🇪",
    "polish": "🇵🇱", "russian": "🇷🇺", "ukrainian": "🇺🇦", "caribbean": "🌴",
    "mediterranean": "🫒", "african": "🌍", "latin": "🌎", "asian": "🌏",
    "fusion": "🔀", "comfort": "🏠",
}

# Signature ingredients per cuisine for matching
CUISINE_SIGNATURES = {
    "thai": ["lemongrass", "coconut milk", "fish sauce", "thai basil", "galangal", "lime", "chili", "coriander", "rice noodles"],
    "chinese": ["soy sauce", "ginger", "sesame oil", "rice vinegar", "star anise", "five spice", "tofu", "oyster sauce", "sichuan pepper"],
    "japanese": ["soy sauce", "mirin", "sake", "rice vinegar", "miso", "nori", "wasabi", "panko", "dashi"],
    "korean": ["gochujang", "kimchi", "sesame oil", "soy sauce", "rice vinegar", "garlic", "scallions", "tofu"],
    "indian": ["garam masala", "turmeric", "cumin", "coriander powder", "ginger", "garlic", "ghee", "mustard seeds", "curry leaves", "fenugreek"],
    "italian": ["olive oil", "parmesan", "basil", "oregano", "tomato", "garlic", "balsamic vinegar", "pasta", "mozzarella"],
    "mexican": ["cumin", "chili powder", "cilantro", "lime", "avocado", "tortilla", "jalapeno", "salsa", "black beans"],
    "french": ["butter", "cream", "white wine", "thyme", "rosemary", "tarragon", "shallot", "dijon mustard", "bay leaf"],
    "moroccan": ["cumin", "cinnamon", "saffron", "preserved lemon", "couscous", "chickpeas", "raisins", "harissa", "coriander"],
    "ethiopian": ["berbere", "niter kibbeh", "teff", "lentils", "onion", "garlic", "ginger", "fenugreek", "cardamom"],
    "nigerian": ["scotch bonnet", "palm oil", "black-eyed peas", "plantain", "crayfish", "ogiri", "suya spice", "groundnut"],
    "lebanese": ["tahini", "lemon", "olive oil", "zaatar", "sumac", "pomegranate molasses", "chickpeas", "bulgur", "mint"],
    "japanese": ["soy sauce", "mirin", "sake", "rice vinegar", "miso", "nori", "wasabi", "panko", "dashi"],
    "greek": ["olive oil", "feta", "oregano", "lemon", "yogurt", "cucumber", "dill", "mint", "phyllo"],
    "vietnamese": ["fish sauce", "rice vinegar", "lemon", "chili", "mint", "cilantro", "rice noodles", "star anise", "lemongrass"],
    "indonesian": ["sambal", "soy sauce", "coconut milk", "lemongrass", "galangal", "tamarind", "palm sugar", "kaffir lime"],
    "brazilian": ["black beans", "cassava", "coconut milk", "dende oil", "lime", "cilantro", "cumin", "paprika"],
    "peruvian": ["aji amarillo", "lime", "cilantro", "corn", "potato", "quinoa", "soy sauce", "rice vinegar"],
    "jamaican": ["scotch bonnet", "allspice", "thyme", "scallion", "garlic", "ginger", "lime", "coconut milk"],
}

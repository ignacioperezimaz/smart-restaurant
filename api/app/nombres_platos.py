"""Nombres y categorías de los platos de la carta.

OJO: los datos del proyecto (sintéticos) solo traen un número por plato (`id_plato`, de 1 a 80), no su nombre.
Estos nombres y categorías los hemos puesto nosotros para que la interfaz sea legible: son nombres de ejemplo de cocina vasca
y NO salen de los datos. Si un día los datos traen los nombres reales, basta con cambiar estas listas (el orden es el del id: el primero es el plato 1).
(La columna `categoria` de las ventas no sirve para esto: cambia de una fila a otra para el mismo plato, así que la fijamos aquí por plato.)
"""
NOMBRES = [
    "Ensalada de tomate y bonito", "Croquetas de jamón", "Tortilla de patatas", "Pimientos de Gernika", "Gildas",
    "Marmitako de bonito", "Bacalao al pil-pil", "Merluza en salsa verde", "Chipirones en su tinta", "Txangurro gratinado",
    "Kokotxas de merluza", "Rabo de toro", "Chuletón a la brasa", "Cordero asado", "Albóndigas en salsa",
    "Alubias de Tolosa", "Puerros con vinagreta", "Ensalada de ventresca", "Sopa de pescado", "Revuelto de hongos",
    "Croquetas de bacalao", "Croquetas de txangurro", "Tortilla de bacalao", "Pintxo de txistorra", "Anchoas del Cantábrico",
    "Ensaladilla rusa", "Tosta de foie", "Jamón ibérico", "Queso Idiazabal con membrillo", "Huevos rotos con jamón",
    "Pulpo a la brasa", "Calamares fritos", "Mejillones al vapor", "Almejas a la marinera", "Rape a la donostiarra",
    "Besugo al horno", "Salmón a la plancha", "Dorada a la sal", "Bonito con tomate", "Sardinas a la brasa",
    "Lubina a la parrilla", "Rodaballo asado", "Cocochas al pil-pil", "Ventresca de bonito", "Pastel de cabracho",
    "Pollo al ajillo", "Pollo en pepitoria", "Solomillo a la pimienta", "Entrecot con patatas", "Carrilleras al vino tinto",
    "Costillas de cerdo glaseadas", "Callos a la vizcaína", "Lengua en salsa", "Manitas de cerdo", "Morcilla de Beasain",
    "Txistorra a la sidra", "Cocido montañés", "Olla podrida", "Porrusalda", "Sopa de cebolla",
    "Crema de calabaza", "Menestra de verduras", "Pisto con huevo", "Alcachofas salteadas", "Espárragos de Navarra",
    "Ensalada de endivias", "Ensalada de queso de cabra", "Tarta de queso", "Goxua", "Pantxineta",
    "Arroz con leche", "Natillas caseras", "Flan de huevo", "Cuajada con miel", "Tarta de manzana",
    "Intxaursaltsa", "Torrijas", "Brownie de chocolate", "Helado de turrón", "Fruta de temporada",
]
# e = entrante, p = principal, o = postre; una letra por plato, en el mismo orden que NOMBRES
_CODIGOS = "eeeee" "pppp" "e" "pppppp" + "e" * 14 + "p" + "eee" + "p" * 8 + "eee" + "p" * 9 + "ee" + "pp" + "e" * 9 + "o" * 13
CATEGORIAS = [{"e": "entrante", "p": "principal", "o": "postre"}[c] for c in _CODIGOS]
assert len(NOMBRES) == 80 and len(CATEGORIAS) == 80 and len(set(NOMBRES)) == 80, "tiene que haber 80 nombres distintos (uno por plato)"


def nombre_de(id_plato: int) -> str:
    """Nombre del plato con ese id; si el id no está en la lista (carta más larga) se devuelve «Plato N»."""
    return NOMBRES[id_plato - 1] if 1 <= id_plato <= len(NOMBRES) else f"Plato {id_plato}"


def categoria_de(id_plato: int) -> str | None:
    """Categoría del plato (entrante, principal o postre); `None` si el id no está en la lista."""
    return CATEGORIAS[id_plato - 1] if 1 <= id_plato <= len(CATEGORIAS) else None

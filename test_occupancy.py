"""Casos reales de vocabulario inmobiliario, para no filtrar de mas ni de menos."""
from radar.occupancy import detect

CASOS = [
    # (texto, esperado)
    ("Piso reformado, se entrega libre de ocupantes y cargas", False),
    ("Vivienda ocupada. No se puede visitar.", True),
    ("Inmueble OCUPADO ilegalmente, precio muy por debajo de mercado", True),
    ("Se vende piso sin posesión, no visitable", True),
    ("Piso alquilado con rentabilidad garantizada del 6%", True),
    ("Se vende nuda propiedad, usufructuaria de 80 años", True),
    ("Ático luminoso con 3 dormitorios y 2 baños, listo para entrar a vivir", False),
    ("Piso a la venta en subasta judicial", True),
    ("Vivienda con inquilinos hasta 2027", True),
    ("Casa con 4 dormitorios, garaje y piscina. Llámanos para concertar visita", False),
    ("Piso céntrico, 3 hab, 2 baños, ascensor", None),
    ("Amplio piso, la ocupación máxima del edificio es de 40 vecinos", None),
    ("Se vende proindiviso del 50%", True),
    ("Vivienda desocupada desde 2020, disponibilidad inmediata", False),
]

def main():
    fallos = 0
    for texto, esperado in CASOS:
        got, motivo = detect(texto)
        ok = got is esperado
        if not ok:
            fallos += 1
        print(f"{'OK ' if ok else 'FALLO'} esperado={esperado!s:<5} obtenido={got!s:<5} {motivo:<40} | {texto[:60]}")
    print(f"\n{len(CASOS) - fallos}/{len(CASOS)} correctos")
    return 1 if fallos else 0

if __name__ == "__main__":
    raise SystemExit(main())

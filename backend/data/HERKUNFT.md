# Woher `off-katalog-dach.csv.gz` kommt

Diese Datei ist ein **Auszug aus der Datenbank von [Open Food Facts](https://openfoodfacts.org)**
und steht unter der [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Die einzelnen Inhalte stehen unter der
[Database Contents License (DbCL) v1.0](https://opendatacommons.org/licenses/dbcl/1-0/).

Erzeugt aus dem täglichen Gesamtabzug
(`https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz`)
mit `backend/scripts/off_katalog.py`. Behalten wurden Produkte, die in
Deutschland, Österreich oder der Schweiz erhältlich sind, einen Strichcode,
einen Namen und eine Kalorienangabe haben — aus 4.535.553 Einträgen wurden
308.070. Übernommen sind nur Strichcode, Name, Marke, Grundeinheit, acht
Nährwerte je 100 g/ml, die Portionsangabe und der Zeitpunkt der letzten
Änderung.

**Warum diese Datei hier liegt:** Dieses Repo ist öffentlich, und damit ist
das Ablegen eines Auszugs eine Weitergabe der Datenbank. Die ODbL erlaubt
das ausdrücklich und verlangt dafür zwei Dinge: die Quelle nennen und die
abgeleitete Datenbank unter derselben Lizenz weitergeben. Genau dafür steht
diese Datei hier — sie ist die Nennung, und die Lizenz oben gilt für den
Auszug wie für das Original.

Sie enthält **keine personenbezogenen Daten**: nur Produktangaben, keine
Nutzer, keine Beiträge einzelner Personen.

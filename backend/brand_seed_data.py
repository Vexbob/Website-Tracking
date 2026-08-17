"""Marken-Seed-Daten fuer Ausgaben-Modul (v1.16.0).

Die Liste ist so kompakt wie moeglich gehalten: pro Marke ``(name, is_private_label,
store_name_hint, parent_company)``. Beim Seeden pro User wird ``store_name_hint``
gegen die vorhandenen Laeden des Users case-insensitive gematcht (via
``LOWER(name)``) — nicht gefundene Zuordnungen lassen ``store_id`` NULL.

Der Seeder ist idempotent (``ON CONFLICT DO NOTHING`` auf ``uniq_brands_user_name``).

Quellen: vom User zusammengestellte Marken-Liste (Session 3).
"""
from __future__ import annotations

# ------------------------------------------------------------------
# 1) EIGENMARKEN pro Laden
#    Format: (marke, store_hint)
# ------------------------------------------------------------------
PRIVATE_LABELS: list[tuple[str, str]] = [
    # ----- ALDI / HOFER (viele Marken geteilt) -----
    ("Milsani","Aldi"),("Milfina","Aldi"),("Milbona","Aldi"),
    ("Hofburger","Aldi"),("Moser Roth","Aldi"),("Choceur","Aldi"),
    ("Choceur Chocolat","Aldi"),("Moser Roth Chocolatier","Aldi"),
    ("Goldaehren","Aldi"),("Gut Drei Eichen","Aldi"),
    ("Pizza Ah","Aldi"),("Karlskrone","Aldi"),
    ("Tandil","Aldi"),("Lacura","Aldi"),("Lacura Medical","Aldi"),
    ("Barissimo","Aldi"),("Biscotto","Aldi"),("Biscotto Mulino","Aldi"),
    ("All Seasons","Aldi"),("Sontner","Aldi"),("Sonniger","Aldi"),
    ("Gut Bio","Aldi"),("Nur Nur Natur","Aldi"),
    ("Mamia","Aldi"),("Mamia Bio","Aldi"),
    ("Back Family","Aldi"),("Meine Backwelt","Aldi"),
    ("Meine Kuchenwelt","Aldi"),("Meine Kaesetheke","Aldi"),
    ("Meine Metzgerei","Aldi"),
    ("Cucina","Aldi"),("Gourmet","Aldi"),
    ("Gourmet Finest Cuisine","Aldi"),("BBQ","Aldi"),
    ("Fair & Gut","Aldi"),("Rio D'Oro","Aldi"),("Le Gusto","Aldi"),
    ("Almare","Aldi"),("Almare Seafood","Aldi"),
    ("Golden Seafood","Aldi"),("Gueldenhof","Aldi"),
    ("Landfreude","Aldi"),("Natur Lieblinge","Aldi"),
    ("Kleine Schaetze","Aldi"),("Wonnemeyer","Aldi"),("Wintertraum","Aldi"),
    ("Roi de Trefle","Aldi"),("My Vay","Aldi"),
    ("Apice Aperitivo","Aldi"),("Cava Delmora","Aldi"),
    ("Muehlengold","Aldi"),("Expressi","Aldi"),
    ("Einfach Regional","Aldi"),("Landvogt","Aldi"),
    ("Monarc","Aldi"),("Olivia","Aldi"),("Ombra Sun","Aldi"),
    ("Zekol","Aldi"),("Kokett","Aldi"),("Amaroy","Aldi"),
    ("Sweet Valley","Aldi"),("Lyttos","Aldi"),("Goldland","Aldi"),
    ("Gartenkrone","Aldi"),("Vitalis","Aldi"),
    ("Crane","Aldi"),("Ambiano","Aldi"),("Ferrex","Aldi"),
    ("Workzone","Aldi"),("Easy Home","Aldi"),("Adventurini","Aldi"),
    ("Mein Veggie Tag","Aldi"),("Mucci","Aldi"),("Satessa","Aldi"),
    ("Quellbrunn","Aldi"),("River","Aldi"),("Flemming","Aldi"),
    ("Favorina","Aldi"),("Schlossberg","Aldi"),
    ("Nuernberger","Aldi"),("Goldhorn","Aldi"),("Kings Crown","Aldi"),
    ("Delicato","Aldi"),("Sahnefest","Aldi"),("Pottkieker","Aldi"),
]

# ----- HOFER (Oesterreich) -----
PRIVATE_LABELS += [
    ("Zurueck zum Ursprung","Hofer"),("bio natura","Hofer"),
    ("NATUR aktiv","Hofer"),("Just Taste","Hofer"),
    ("FairHOF","Hofer"),("Sonnhof","Hofer"),
    ("Sonnhof BBQ","Hofer"),("Prio","Hofer"),
    ("HOFER Marktplatz","Hofer"),("Ein gutes Stueck Heimat","Hofer"),
    ("Backbox","Hofer"),("Gutes vom Baecker","Hofer"),
    ("Gutes aus der Region","Hofer"),
    ("Genuss 100% aus Oesterreich","Hofer"),("Genuss","Hofer"),
    ("Good Choice","Hofer"),("Primana","Hofer"),
    ("Nature's Gold","Hofer"),("Snack Fun","Hofer"),
    ("Finest Bakery","Hofer"),("Pure Fruits","Hofer"),
    ("HoT","Hofer"),("RETTERSWERT","Hofer"),
]

# ----- LIDL -----
PRIVATE_LABELS += [
    ("Milbona Selection","Lidl"),("Dulano","Lidl"),("Dulano Light","Lidl"),
    ("Landjunker","Lidl"),("Metzgerfrisch","Lidl"),
    ("Grillmeister","Lidl"),("Vitakrone","Lidl"),
    ("Grafschafter","Lidl"),("Unser Brot","Lidl"),
    ("Sondey","Lidl"),("Sondey Captain Rondo","Lidl"),
    ("Mister Choc","Lidl"),("Bon Gelati","Lidl"),("Gelatelli","Lidl"),
    ("Ocean Traders","Lidl"),("Ocean Sea","Lidl"),
    ("Freshona","Lidl"),("Golden Sun","Lidl"),("Combino","Lidl"),
    ("Crownfield","Lidl"),("Belbake","Lidl"),("Nudelhof","Lidl"),
    ("Kania","Lidl"),("Chef Select","Lidl"),
    ("Chef Select To Go","Lidl"),("Select & Go","Lidl"),
    ("Vita d'Or","Lidl"),("Primadonna","Lidl"),
    ("Baresa","Lidl"),("Desira","Lidl"),("KingFrais","Lidl"),
    ("Favorini","Lidl"),("J.D. Gross","Lidl"),
    ("Confiserie Firenze","Lidl"),("Fin Carre","Lidl"),("Nautica","Lidl"),
    ("Pianola","Lidl"),("Pic Frisch","Lidl"),("Crusti Croc","Lidl"),
    ("SunSnacks","Lidl"),("HappyMix","Lidl"),("Amidala","Lidl"),
    ("Choco Nussa","Lidl"),("Reichsgraf","Lidl"),
    ("Goldfield","Lidl"),("Templeton","Lidl"),
    ("Bellarom","Lidl"),("Lord Nelson","Lidl"),
    ("Freeway","Lidl"),("Solevita","Lidl"),
    ("Kong Strong","Lidl"),("Saskia","Lidl"),
    ("Perlenbacher","Lidl"),("Bergadler","Lidl"),
    ("Cimarosa","Lidl"),("L'arivee blanc","Lidl"),
    ("Bitterol","Lidl"),("Marahon","Lidl"),
    ("Vitasia","Lidl"),("Italiamo","Lidl"),
    ("McEnnedy","Lidl"),("Eridanous","Lidl"),
    ("1001 Delights","Lidl"),("Alma Latina","Lidl"),
    ("Alpen Fest","Lidl"),("Duc de Coeur","Lidl"),
    ("El Tequito","Lidl"),("Trattoria Alfredo","Lidl"),
    ("La Cestera","Lidl"),("La Caldera","Lidl"),
    ("Sweet Corner","Lidl"),("Ernesto","Lidl"),
    ("Culinea","Lidl"),("Chene D'Argent","Lidl"),
    ("Meine Kaeserei","Lidl"),("Wild Kueche","Lidl"),
    ("My best Veggie","Lidl"),("Atlantic","Lidl"),
    ("Petri","Lidl"),("Trawlic","Lidl"),
    ("Sol & Mar","Lidl"),("Nixe","Lidl"),
    ("Nostja","Lidl"),("Baroni","Lidl"),
    ("Gebirgsjaeger","Lidl"),("Boerdegold","Lidl"),
    ("Feine Kost","Lidl"),("Harvest Basket","Lidl"),
    ("Campo Largo","Lidl"),("Realvalle","Lidl"),
    ("Purio","Lidl"),("Olisone","Lidl"),
    ("Roncero","Lidl"),("Naturis","Lidl"),
    ("Monissa","Lidl"),("Maribel","Lidl"),
    ("Origen y Tradicion","Lidl"),("Sabores de tradicion","Lidl"),
    ("Vemondo","Lidl"),("Deluxe","Lidl"),
    ("Fairglobe","Lidl"),("Linessa","Lidl"),("Meradiso","Lidl"),
    ("Cien","Lidl"),("Cien Sun","Lidl"),("Dentalux","Lidl"),
    ("Floralys","Lidl"),("G. Bellini","Lidl"),
    ("Siempre","Lidl"),("Suddenly","Lidl"),
    ("Optisana","Lidl"),("Nevadent","Lidl"),
    ("W5","Lidl"),("Formil","Lidl"),
    ("Maxitrat","Lidl"),("doussy","Lidl"),
    ("Silvercrest","Lidl"),("Crivit","Lidl"),("Parkside","Lidl"),
    ("Lupilu","Lidl"),("Esmara","Lidl"),
    ("Livergy","Lidl"),("pepperts!","Lidl"),
    ("Melinera","Lidl"),("Livarno","Lidl"),
    ("Ultimate Speed","Lidl"),("Miomare","Lidl"),
    ("Florabest","Lidl"),("Footflexx","Lidl"),
    ("Sensiplast","Lidl"),("Playtive","Lidl"),
    ("Powerfix","Lidl"),("Rocktrail","Lidl"),
    ("Topmove","Lidl"),("Tronic","Lidl"),
    ("Auriol","Lidl"),("Cassetti","Lidl"),
    ("Crelando","Lidl"),("Argus","Lidl"),
    ("United Office","Lidl"),("Nobel Leage","Lidl"),
]

# ----- KAUFLAND -----
PRIVATE_LABELS += [
    ("K-Classic","Kaufland"),("K-Bio","Kaufland"),
    ("K-Bio Organic","Kaufland"),("K-Gold Edition","Kaufland"),
    ("K-Plant Based","Kaufland"),("K-Purland","Kaufland"),
    ("K-Wertschaetze","Kaufland"),("K-To Go","Kaufland"),
    ("K-Blue Bay","Kaufland"),("K-Free Glutenfrei","Kaufland"),
    ("K-Free Laktosefrei","Kaufland"),("K-Wat","Kaufland"),
    ("K-Concept+","Kaufland"),("Exquisit","Kaufland"),
    ("Beviva","Kaufland"),("Pepps","Kaufland"),
    ("Grotemeyer's Konditorei","Kaufland"),("Sottrum's","Kaufland"),
    ("Wippler","Kaufland"),("Let's BBQ","Kaufland"),
    ("Crazy Wolf","Kaufland"),("Stephans Braeu","Kaufland"),
    ("Hochsteiner","Kaufland"),("Ries-ling","Kaufland"),
    ("Amaris","Kaufland"),("Purvello","Kaufland"),
    ("bevola","Kaufland"),("Countryside","Kaufland"),
    ("Hip & Hopps","Kaufland"),("Townland","Kaufland"),
    ("Oyanda","Kaufland"),("Kidland","Kaufland"),
    ("Kuniboo","Kaufland"),("Liv&Bo","Kaufland"),
    ("MyProject","Kaufland"),("Newcential","Kaufland"),
    ("Spice&Soul","Kaufland"),("Switch On","Kaufland"),
    ("Talentus","Kaufland"),
]

# ----- PENNY -----
PRIVATE_LABELS += [
    ("Penny Ready","Penny"),("Milprima","Penny"),
    ("Baeckerkroenung","Penny"),("San Fabio","Penny"),
    ("Lindenhof","Penny"),("Naturgut","Penny"),
    ("Naturkind","Penny"),("Muehlenhof","Penny"),
    ("Food For Future","Penny"),("Butcher's by Penny","Penny"),
    ("Magico","Penny"),("Mayfair","Penny"),
    ("today","Penny"),("blik","Penny"),
    ("Chocola","Penny"),("Mike Mitchell's","Penny"),
    ("Olivers","Penny"),("Elite","Penny"),
    ("Landmark","Penny"),("Mitakos","Penny"),
    ("Berida","Penny"),("Ich bin Oesterreich","Penny"),
]

# ----- BILLA -----
PRIVATE_LABELS += [
    ("clever","Billa"),("Ja! Natuerlich","Billa"),
    ("BILLA Bio","Billa"),("BILLA Genusswelt","Billa"),
    ("Da komm' ich her!","Billa"),("FranzLeopold","Billa"),
    ("Hofstaedter","Billa"),("Larsini","Billa"),
    ("Tonis Freilandeier","Billa"),("Vegavita","Billa"),
    ("Full Speed","Billa"),("Free","Billa"),
    ("Wunderlinge","Billa"),("Erste Sahne","Billa"),
    ("Wegenstein","Billa"),
]

# ----- SPAR -----
PRIVATE_LABELS += [
    ("S-Budget","Spar"),("SPAR Qualitaetsmarke","Spar"),
    ("SPAR Premium","Spar"),("SPAR Natur*pur","Spar"),
    ("Spar Vital","Spar"),("Spar Veggie","Spar"),
    ("Spar free from","Spar"),("Spar enjoy","Spar"),
    ("Spar BBQ","Spar"),("Despar","Spar"),
    ("SparQ","Spar"),("Spar Caffe","Spar"),
    ("REGIO","Spar"),("Herzensgut","Spar"),
    ("TANN","Spar"),("S-Baecker","Spar"),
    ("Marke Ja!","Spar"),
]

# ----- BIPA -----
PRIVATE_LABELS += [
    ("bi good","Bipa"),("BABYWELL","Bipa"),
    ("BI LIFE","Bipa"),("BI LIFE DENT","Bipa"),
    ("LOOK BY BIPA","Bipa"),("BI CARE","Bipa"),
    ("BI HOME","Bipa"),("BI COMFORT","Bipa"),
]

# ----- SUTTERLUETY / ADEG / DENN'S -----
PRIVATE_LABELS += [
    ("Sutterluety","Sutterluety"),("Sutter's Bio","Sutterluety"),
    ("Sutter's Gourmet","Sutterluety"),("Sutter's Natur","Sutterluety"),
    ("Sutter's Backstube","Sutterluety"),
    ("ADEG Eigenmarke","Adeg"),("ADEG Gourmet","Adeg"),("ADEG Bio","Adeg"),
    ("denn's Bio","Denn's"),("dennree","Denn's"),
    ("denn's Vegan","Denn's"),("denn's Hausmarke","Denn's"),
]

# ----- dm -----
PRIVATE_LABELS += [
    ("alverde NATURKOSMETIK","dm"),("alverde Color & Care","dm"),
    ("Balea","dm"),("Balea MEN","dm"),
    ("reell'e","dm"),("Dontodent","dm"),
    ("Mivolis","dm"),("visiomax","dm"),
    ("Denkmit","dm"),("Profissimo","dm"),
    ("Saugstark & Sicher","dm"),("Soft & Sicher","dm"),
    ("Sanft & Sicher","dm"),("dmBio","dm"),
    ("Sportness","dm"),("Ivorell","dm"),
    ("ebelin","dm"),("trend !t up","dm"),
    ("babylove","dm"),("ALANA","dm"),
    ("Pusblu","dm"),("SauBaer","dm"),
    ("Fascino","dm"),("Paradies","dm"),
    ("SEINZ.","dm"),("s.he stylezone","dm"),
]

# ----- ROSSMANN -----
PRIVATE_LABELS += [
    ("ISANA","Rossmann"),("alouette","Rossmann"),
    ("Alterra","Rossmann"),("altapharma","Rossmann"),
    ("enerBiO","Rossmann"),("domol","Rossmann"),
    ("Rival de Loop","Rossmann"),("facelle","Rossmann"),
    ("Sunozon","Rossmann"),("Babydream","Rossmann"),
    ("IDEENWELT","Rossmann"),("Nabio","Rossmann"),
]

# ----- MUELLER / NORMA / GLOBUS -----
PRIVATE_LABELS += [
    ("BIO PRIMO","Mueller"),("SoftStar","Mueller"),
    ("CleanPac","Mueller"),("Blink","Mueller"),("LAVOZON","Mueller"),
    ("my smile","Norma"),("Fjordkrone","Norma"),
    ("vitafit","Norma"),("time to taste","Norma"),
    ("Finca del Sol","Norma"),("Bio Sonne","Norma"),
    ("La Bonesse","Norma"),("Hofgut Sternen","Norma"),
    ("Globus VdQ","Globus"),("Globus Bio","Globus"),
    ("Globus GenussWelt","Globus"),
]
BRANDS: list[tuple[str, str | None]] = [
    # --- Milch & Molkereiprodukte ---
    ("Mueller Milch",None),("Mueller Milchreis",None),
    ("Zott",None),("Zott Monte",None),
    ("Arla",None),("Arla Castello",None),
    ("Hochland",None),("Oldenburger",None),("Meggle",None),
    ("Weihenstephan",None),("Bauer",None),("Milram",None),
    ("Exquisa",None),("Karwendel",None),("Hansano",None),
    ("Le President",None),("Bergader",None),("Bonifaz",None),
    ("Galbani",None),("Castello",None),
    ("Hirten",None),("Tirol Milch",None),("Schaerdinger",None),
    ("Berchtesgadener",None),("Landliebe",None),
    ("Bresso",None),("Miree",None),("Almette",None),
    ("La Vache qui rit",None),("Milkana",None),
    ("Mini Babybel",None),
    ("Gervais",None),("Emmi",None),("Andechser Natur",None),
    ("Vorarlberg Milch",None),
    ("Berchtesgadener Land",None),("Almdudler",None),
    ("NOEM",None),("Rupp",None),("Merkur",None),
    # --- Brot & Backwaren ---
    ("Brandt",None),("Golden Toast",None),("Lieken",None),
    ("Lieken Urkorn",None),("Leibniz","Bahlsen"),
    ("Coppenrath & Wiese",None),("Dr. Oetker",None),
    ("Kuchenmeister",None),("Knack & Back",None),
    ("Anker",None),("Ruetz",None),
    ("Resch & Frisch",None),("Wolfer",None),("Schaefer",None),
    ("Der Beck",None),("Harry",None),("Kamps",None),
    ("Ditsch",None),("BackWerk",None),
    ("Manner",None),("Manner Schnitten",None),
    ("Wachauer Schnitten",None),("Niemetz",None),
    ("Schwedenbomben",None),("Radatz",None),
]

# --- Suesswaren & Schokolade ---
BRANDS += [
    ("Milka","Mondelez"),("Ritter Sport",None),("Ritter Sport Mini",None),
    ("Lindt","Lindt & Spruengli"),("Lindt Lindor","Lindt & Spruengli"),
    ("Ferrero","Ferrero"),("Kinder","Ferrero"),("Nutella","Ferrero"),
    ("Duplo","Ferrero"),("Hanuta","Ferrero"),("Mon Cheri","Ferrero"),
    ("Ferrero Rocher","Ferrero"),("Raffaello","Ferrero"),
    ("Kinder Schoko-Bons","Ferrero"),("Kinder Bueno","Ferrero"),
    ("Kinder Country","Ferrero"),("Kinder Happy Hippo","Ferrero"),
    ("Kinder Maxi King","Ferrero"),
    ("Mars","Mars"),("Snickers","Mars"),("Twix","Mars"),
    ("Bounty","Mars"),("M&M's","Mars"),("Maltesers","Mars"),
    ("KitKat","Nestle"),("Smarties","Nestle"),("Lion","Nestle"),
    ("After Eight","Nestle"),("Choco Crossies","Nestle"),
    ("Nuts","Nestle"),("Rolo","Nestle"),("YES Torty","Nestle"),
    ("Caramac","Nestle"),
    ("August Storck",None),("Storck Riesen",None),
    ("Merci",None),("Toffifee",None),("Werther's Original",None),
    ("Bahlsen","Bahlsen"),("Choco Leibniz","Bahlsen"),
    ("Waffeletten","Bahlsen"),("PickUp","Bahlsen"),
    ("Haribo","Haribo"),("Haribo Goldbaeren","Haribo"),
    ("Trolli",None),("Nimm2","Storck"),("Ricola",None),
    ("Toblerone","Mondelez"),("Oreo","Mondelez"),
    ("Philadelphia","Mondelez"),("Tassimo","Mondelez"),
    ("Suchard","Mondelez"),
    ("Schogetten",None),("Sarotti",None),("Stollwerck",None),
    ("Knoppers",None),("Griesson-de Beukelaer",None),
    ("Prinzenrolle",None),("Lambertz",None),
]

# --- Fleisch, Fisch, Aufstriche ---
BRANDS += [
    ("Boeklunder",None),("Gutfried",None),("Reinert",None),
    ("Stockmeyer",None),("Herta","Nestle"),
    ("Homann",None),("Popp",None),("Wiesenhof",None),
    ("Wiesbauer",None),("Toennies",None),("Frosta",None),
    ("Koenecke",None),("Ruegenwalder",None),
    ("Iglo","Iglo"),("Iglo Fischstaebchen","Iglo"),
    ("Findus",None),("Bonduelle",None),("Costa",None),
    ("Nordsee",None),
    ("Zentis",None),("Schwartau",None),("Stute",None),
    ("Bebel",None),("Hero",None),("Bon Maman",None),
    ("Werder Frucht",None),("Darbo",None),("Staud",None),
]

# --- Kaffee & Tee, Getraenke ---
BRANDS += [
    ("Dallmayr",None),("Dallmayr Prodomo",None),
    ("Jacobs","Mondelez"),("Jacobs Kroenung","Mondelez"),
    ("Lavazza",None),("Illy",None),("Segafredo",None),
    ("Melitta",None),("Onko",None),("Tchibo",None),
    ("Eduscho",None),("Krueger",None),
    ("Teekanne",None),("Messmer",None),
    ("Hohes C",None),("alnatura","Alnatura"),
    ("Julius Meinl",None),("Lipton","Unilever"),
    ("Pickwick",None),("Yogi Tea",None),("Tee Gschwendner",None),
    ("Nespresso","Nestle"),("Nescafe","Nestle"),
    ("Coca-Cola","Coca-Cola"),("Coca-Cola Zero","Coca-Cola"),
    ("Coca-Cola Light","Coca-Cola"),
    ("Pepsi",None),("Pepsi Max",None),
    ("Sprite","Coca-Cola"),("Fanta","Coca-Cola"),
    ("Mezzo Mix","Coca-Cola"),("Club-Mate",None),
    ("Mio Mio Mate",None),("Bionade",None),("Fritz-Kola",None),
    ("Capri-Sun",None),("Albi",None),("Granini",None),
    ("Voelkel",None),("Rabenhorst",None),
    ("Warsteiner",None),("Bitburger",None),("Beck's",None),
    ("Heineken",None),("Paulaner",None),("Erdinger",None),
    ("Augustiner",None),("Ottakringer",None),("Stiegl",None),
    ("Murauer",None),("Zipfer",None),("Puntigamer",None),
    ("Goesser",None),("Villacher",None),("Schwechater",None),
    ("Kaiser",None),("Freistaedter",None),("Wieselburger",None),
    ("Moenchshof",None),("Eichbaum",None),("Koestritzer",None),
    ("Schoefferhofer",None),("Franziskaner",None),("Tegernseer",None),
    ("Weihenstephaner",None),("Radeberger",None),
    ("Pilsner Urquell",None),
    ("Red Bull",None),("Monster",None),("Rockstar",None),
    ("Roemerquelle",None),("Cappy","Coca-Cola"),
    ("Fuzetea","Coca-Cola"),("Innocent","Coca-Cola"),
    ("Schweppes",None),("Evian","Danone"),("Volvic","Danone"),
    ("San Pellegrino","Nestle"),("Acqua Panna","Nestle"),
    ("Gerolsteiner",None),("Adelholzener",None),
    ("Voeslauer",None),
]

# --- TK/Obst/Gemuese, Pasta, Reis, Fertig, Snacks ---
BRANDS += [
    ("Bofrost",None),("Frostkrone",None),("Spreewaldhof",None),
    ("Dole",None),("Chiquita",None),("Del Monte",None),("Pfanni",None),
    ("Barilla",None),("Buitoni","Nestle"),("De Cecco",None),
    ("Garofalo",None),("Maggi","Nestle"),("Birkel",None),
    ("Bechtle",None),("3 Glocken",None),
    ("Ben's Original","Mars"),("Uncle Ben's","Mars"),
    ("Knorr","Unilever"),("Erasco",None),("Heinz",None),
    ("Buss",None),("Hela",None),("Kuepper",None),
    ("Maggi Fix","Nestle"),("Hellmann's","Unilever"),
    ("Mondamin","Unilever"),("Thomy","Unilever"),
    ("Becel","Unilever"),("Rama","Unilever"),
    ("Lorenz",None),("Chio",None),("Funny Frisch",None),
    ("Pom-Baer",None),("Pringles",None),("Saltletts",None),
    ("Soletti",None),("Kelly's",None),("Zweifel",None),
    ("Utz",None),("Pfeiffer",None),
]

# --- Wasch/Reinigung ---
BRANDS += [
    ("Persil","Henkel"),("Ariel","P&G"),("Lenor","P&G"),
    ("Vernel","Henkel"),("Perwoll","Henkel"),
    ("Somat","Henkel"),("Pril","Henkel"),("Bref","Henkel"),
    ("Der General","Henkel"),("WC-Frisch","Henkel"),
    ("Sidolin","Henkel"),("Sil","Henkel"),
    ("Weisser Riese","Henkel"),("Spee","Henkel"),
    ("Frosch",None),("K2r",None),
    ("Biff",None),("Cif","Unilever"),("Cillit Bang",None),
    ("Viss","Unilever"),("Sagrotan",None),
    ("Domestos","Unilever"),("Coral","Unilever"),
    ("Meister Proper","P&G"),("Antikal","P&G"),
    ("Fairy","P&G"),("Febreze","P&G"),("Swiffer","P&G"),
    ("Pattex","Henkel"),("Pritt","Henkel"),
    ("Metylan","Henkel"),("Ponal","Henkel"),
    ("Ceresit","Henkel"),("Loctite","Henkel"),
]

# --- Hygiene, Kosmetik, Baby, Bio, Danone ---
BRANDS += [
    ("Nivea","Beiersdorf"),("Dove","Unilever"),("L'Oreal",None),
    ("Garnier","L'Oreal"),("Palmolive",None),("Elvive","L'Oreal"),
    ("Schauma","Henkel"),("Gliss Kur","Henkel"),
    ("Sunsilk","Unilever"),("Fa",None),("Duschdas",None),
    ("Sebamed",None),("Odol",None),("Colgate",None),
    ("Sensodyne",None),("Elmex",None),("Meridol",None),
    ("Dentagard",None),("Blend-a-med","P&G"),("Oral-B","P&G"),
    ("Signal","Unilever"),("Vaseline","Unilever"),
    ("Rexona","Unilever"),("Axe","Unilever"),("Old Spice","P&G"),
    ("Head & Shoulders","P&G"),("Pantene","P&G"),
    ("Taft","Henkel"),("got2b","Henkel"),("Syoss","Henkel"),
    ("Schwarzkopf","Henkel"),("Gillette","P&G"),
    ("Braun","P&G"),("Venus","P&G"),
    ("Always","P&G"),("Pampers","P&G"),("Wick","P&G"),
    ("Zewa","Essity"),("Tempo","Essity"),("Tena","Essity"),
    ("Labello","Beiersdorf"),("8x4","Beiersdorf"),
    ("Weleda",None),("Lavera",None),
    ("Maybelline","L'Oreal"),("Max Factor",None),
    ("Catrice",None),("Essence",None),("NYX",None),
    ("Vichy","L'Oreal"),("La Roche-Posay","L'Oreal"),
    ("Eucerin","Beiersdorf"),("CeraVe","L'Oreal"),
    ("Bioderma",None),("Avene",None),
    ("Hipp",None),("Alete",None),("Bebivita",None),
    ("Milupa","Danone"),("Aptamil","Danone"),
    ("Humana",None),("Nuk",None),("MAM",None),
    ("Ruf",None),("Kotanyi",None),
    ("Bautz'ner",None),("Develey",None),("Haendlmaier",None),
    ("Kuehne",None),("Hengstenberg",None),
    ("Garden Gourmet","Nestle"),("Beyond Meat",None),
    ("Vivera",None),("LikeMeat",None),
    ("The Vegetarian Butcher","Unilever"),("Wheaty",None),
    ("Tofutown",None),("Topas",None),("Taifun",None),
    ("Alnatura","Alnatura"),("Alnavit","Alnatura"),
    ("Demeter",None),("Bioland",None),("Naturland",None),
    ("Rapunzel",None),("Lebensbaum",None),
    ("Sonnentor",None),("Beutelsbacher",None),
    ("Beckers Bester",None),
    ("Actimel","Danone"),("Activia","Danone"),
    ("Danone","Danone"),("Fruchtzwerge","Danone"),
    ("Danette","Danone"),
]


def _dedupe(items: list) -> list:
    """Erlaubt Duplikate in der Quelle (leichter zu pflegen)."""
    seen = set()
    out = []
    for it in items:
        key = it[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# Duplikate aus den Rohlisten entfernen (case-insensitive).
PRIVATE_LABELS = _dedupe(PRIVATE_LABELS)
BRANDS = _dedupe(BRANDS)

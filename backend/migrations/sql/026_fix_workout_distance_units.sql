-- Workout-Distanzen aus dem CSV-Import in Metern korrigieren (v1.40.5)
--
-- Die Workouts-CSV von Auto Health Export beschriftet die Distanz-Spalte immer
-- mit "(km)", liefert fuer Schwimm-Workouts aber HealthKit-Rohwerte in Metern
-- (1800 statt 1,800). Der Ingest hat mit 1000 multipliziert, wodurch ein
-- 1800-m-Bahnschwimmen als 1,8 Mio. Meter (= 1800 km) in der DB landete und
-- die Pace-Kachel 0:02 min/km anzeigte. Der Ingest erkennt den Fall jetzt an
-- der Groessenordnung; diese Migration zieht die bereits importierten Zeilen
-- nach.
--
-- Grenze: 300 km. Darueber liegt keine reale Einzel-Trainingseinheit mehr,
-- darunter bleibt jede echte km-Angabe (Marathon, Radtour) unangetastet.

UPDATE health_workouts
   SET distance_m = distance_m / 1000
 WHERE distance_m > 300000;

-- Dieselbe Umrechnung fuer die Zusatzmetriken: die Geschwindigkeit stammt aus
-- derselben Spalte und stand entsprechend als 1580 statt 1,58 km/h drin.
UPDATE health_workout_metrics
   SET value = value / 1000
 WHERE metric_key IN ('avg_speed_kmh', 'max_speed_kmh')
   AND value > 100;

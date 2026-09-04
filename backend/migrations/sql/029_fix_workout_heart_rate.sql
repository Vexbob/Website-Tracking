-- Unplausible Workout-Pulswerte aus dem CSV-Import bereinigen (v1.43.2)
--
-- Die Workouts-CSV von Auto Health Export enthaelt neben "Durchschn.
-- Herzfrequenz (bpm)" auch "Durchschn. Herzfrequenzvariabilitaet (ms)".
-- Die Spaltensuche des Ingest hat nach den Stichworten "Durchschn." UND
-- "Herzfrequenz" gesucht -- beides trifft auch auf die HRV-Spalte zu. Stand
-- sie im Export weiter vorn, landeten HRV-Millisekunden (typisch 5-80) als
-- Puls in der DB; die Ø-Puls-Kachel zeigte dadurch 8 bpm.
--
-- Der Ingest ueberspringt HRV-Header inzwischen und verwirft ausserdem
-- unplausible Werte. Diese Migration zieht die bereits importierten Zeilen
-- nach: alles ausserhalb 30-240 bpm ist als Puls eines Trainings nicht
-- erklaerbar und wird auf NULL gesetzt, damit es keinen Durchschnitt mehr
-- verfaelscht. Die Zeilen selbst bleiben unangetastet -- ein erneuter Import
-- fuellt den echten Wert per ON CONFLICT DO UPDATE wieder auf.

UPDATE health_workouts
   SET avg_heart_rate = NULL
 WHERE avg_heart_rate IS NOT NULL
   AND (avg_heart_rate < 30 OR avg_heart_rate > 240);

UPDATE health_workouts
   SET max_heart_rate = NULL
 WHERE max_heart_rate IS NOT NULL
   AND (max_heart_rate < 30 OR max_heart_rate > 240);

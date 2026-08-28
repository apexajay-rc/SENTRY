use std::collections::HashMap;

pub struct MarkovEngine {
    // Outer key: Current App. Inner key: Next App. Value: Transition count.
    matrix: HashMap<String, HashMap<String, u64>>,
    
    // The required probability (0.0 to 1.0) before SENTRY acts on a prediction
    confidence_threshold: f64,
}

impl MarkovEngine {
    /// Initializes a new predictive engine with a strict confidence threshold.
    pub fn new(confidence_threshold: f64) -> Self {
        Self {
            matrix: HashMap::new(),
            confidence_threshold,
        }
    }

    /// Logs a window switch event to train the temporal model.
    pub fn record_transition(&mut self, current_app: &str, next_app: &str) {
        // We do not train the model on accidental micro-switches to the same app
        if current_app == next_app { 
            return; 
        } 
        
        let transitions = self.matrix.entry(current_app.to_string()).or_default();
        *transitions.entry(next_app.to_string()).or_insert(0) += 1;
    }

    /// Analyzes current state and predicts the next window focus.
    /// Returns None if the highest probability fails to meet the confidence threshold.
    pub fn predict_next(&self, current_app: &str) -> Option<(String, f64)> {
        let transitions = self.matrix.get(current_app)?;
        
        let total_transitions: u64 = transitions.values().sum();
        if total_transitions == 0 { 
            return None; 
        }

        let mut best_guess = None;
        let mut highest_prob = 0.0;

        // Calculate the highest statistical probability
        for (next_app, &count) in transitions {
            let probability = count as f64 / total_transitions as f64;
            if probability > highest_prob {
                highest_prob = probability;
                best_guess = Some(next_app);
            }
        }

        // The safety check: prevent cache-trashing on low-confidence guesses
        if highest_prob >= self.confidence_threshold {
            Some((best_guess?.clone(), highest_prob))
        } else {
            None
        }
    }

    /// Dumps the current matrix state for debugging and visualization
    pub fn dump_matrix(&self) {
        println!("\n[PREDICTOR] --- Temporal Markov Matrix State ---");
        for (current, transitions) in &self.matrix {
            let total: u64 = transitions.values().sum();
            println!("[PREDICTOR] From '{}' (Total transitions: {}):", current, total);
            
            let mut sorted_transitions: Vec<_> = transitions.iter().collect();
            sorted_transitions.sort_by(|a, b| b.1.cmp(a.1)); // Sort by highest count

            for (next, count) in sorted_transitions {
                let pct = (*count as f64 / total as f64) * 100.0;
                println!("[PREDICTOR]   -> '{}' : {:.1}% ({} times)", next, pct, count);
            }
        }
        println!("[PREDICTOR] ------------------------------------\n");
    }
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_markov_predictions() {
        // Demand an 80% confidence rate before acting
        let mut engine = MarkovEngine::new(0.80);

        // Simulate user workflow: Code -> Firefox -> Alacritty
        engine.record_transition("code", "firefox");
        engine.record_transition("code", "firefox");
        engine.record_transition("code", "firefox");
        engine.record_transition("code", "firefox");
        engine.record_transition("code", "alacritty"); // 4 to Firefox, 1 to Alacritty (80%)

        // Simulate background noise
        engine.record_transition("firefox", "discord");
        engine.record_transition("firefox", "discord");
        engine.record_transition("firefox", "code"); // 2 to Discord, 1 to Code (66%)

        // Test High Confidence (Should predict firefox)
        if let Some((prediction, confidence)) = engine.predict_next("code") {
            assert_eq!(prediction, "firefox");
            assert_eq!(confidence, 0.80);
            println!("Prediction successful! Code -> {} ({:.1}%)", prediction, confidence * 100.0);
        } else {
            panic!("Engine failed to predict despite hitting 80% threshold.");
        }

        // Test Low Confidence (Should return None because 66% < 80%)
        let weak_prediction = engine.predict_next("firefox");
        assert!(weak_prediction.is_none(), "Engine hallucinated a prediction below threshold!");

        engine.dump_matrix();
    }
}

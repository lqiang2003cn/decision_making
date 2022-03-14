## Agent class
# This script contains the active inference agent class. 
# This is ageneral class that uses the aip module which allows to update the mdp structure given an observation and a preference. 
# Initialized using the mdp templates 

import numpy as np
import copy

class AiAgent(object):
    def __init__(self, mdp):
        self._mdp =  mdp    # This contains the mdp structure for the active inference angent

        # Initialization of variables
        self.n_policies = np.shape(self._mdp.V)[0]  # Number of allowable policies
        self.n_states = np.shape(self._mdp.B)[0]  # Number of states
        self.n_actions = np.shape(self._mdp.B)[2]  # Number of controls
        self.n_outcomes = self.n_states  # Number of sensory inputs, same as the states
        self.t_horizon = 2  # Time horizon to look one step ahead
        self.F = np.zeros([self.n_policies, 1])        # Assigning local variables to this instance of the function
        # ------------------------------------------------------------------------------------------------------------------
        self.policy_indexes_v = self._mdp.V  # Indexes of possible policies
        self.policy_post_u = np.zeros([self.n_policies, self.t_horizon])  # Initialize vector to contain posterior probabilities of actions

        # Normalization
        if hasattr(self._mdp, 'D'):
            self._mdp.D = self.aip_norm(self._mdp.D)
        else:
            self._mdp.D = self.aip_norm(np.ones((self.n_states, 1)))

        # Prior preferences (log probabilities) : C
        self._mdp.C = self.aip_log(self.aip_softmax(copy.copy(self._mdp.C)))
        # Preferences over policies
        self._mdp.E = self.aip_log(self.aip_norm(self._mdp.E))

        # Likelihood matrix
        self.likelihood_A = self.aip_norm(self._mdp.A)

        # Transition matrix
        self.fwd_trans_B = np.zeros((self.n_states, self.n_states, self.n_actions))
        self.bwd_trans_B = np.zeros((self.n_states, self.n_states, self.n_actions))

        for action in range(self.n_actions):
            # Retrieve forward messages, B
            self.fwd_trans_B[:, :, action] = self.aip_norm(self._mdp.B[:, :, action])
            # Retrieve backward messages, transpose of B
            self.bwd_trans_B[:, :, action] = np.transpose(self.aip_norm(self._mdp.B[:, :, action]))

        # Putting observations in sparse form, initialization
        self.sparse_O = np.zeros((1, self.n_states, self.t_horizon))  # Outcomes here are indicated as [1 0], [0 1]

        # Posterior states
        # ------------------------------------------------------------------------------------------------------------------
        # Initialize posterior expectation over hidden states
        self.post_x = np.zeros([self.n_states, self.t_horizon, self.n_policies]) + 1.0/self.n_states
        self.sparse_post_X = np.zeros([self.n_states, self.t_horizon])
        self.sparse_post_X[:, 0] = np.transpose(self._mdp.D)
        # Set the current state to what contained in D. At the next step it is still uncertain, so we leave it as that
        for policy in range(self.n_policies):
            self.post_x[:, 0, policy] = np.transpose(self._mdp.D)

    def infer_states(self, obs):
        # Update posterior over hidden states using marginal message passing
        # Requires A, B, list of observations over time, list of policies, prior belief about initia state
        # Returns Posterior beliefs over hidden states for each policy (s_pi_tau), and Variationl free energy for eahc policy 
        
        # Reset sparse observations
        self.sparse_O = np.zeros((1, self.n_states, self.t_horizon))

        for this_policy in range(self.n_policies):  # Loop over the available policies
            self.F[this_policy] = 0  # Reset free energy for this policy 

            for tau in range(self.t_horizon):  # Loop over future time points
                # Determine state and observation sequences
                if tau == 0:  
                    # Initial observation from passed argument obs put it in sparse form: convert scalar index to a "1" in the  corresponding place
                    self.sparse_O[0, obs, tau] = 1
                else:
                    # Sample from likelihood given hidden state. This is equivalent to o = A*s
                    s_tau_past = np.reshape(self.post_x[:, tau - 1, this_policy], (self.n_states, 1))
                    sampled_outcome = np.argmax(np.dot(self.likelihood_A, s_tau_past))
                    self.sparse_O[0, sampled_outcome, tau] = 1

                # Likelihood over outcomes
                if tau <= self.t_horizon:
                    lnA = np.dot(self.aip_log(self.likelihood_A), np.transpose(self.sparse_O[:, :, tau]))     # lnA.o_tau 
                else:
                    lnA = np.zeros([self.n_states, 1])

                # Past messages
                if tau == 0:
                    lnB_past = self.aip_log(self._mdp.D)
                else: 
                    lnB_past = np.dot(self.aip_log(self.fwd_trans_B[:, :, self.policy_indexes_v[this_policy]]), s_tau_past) 

                # Future message
                if tau >= self.t_horizon -1:
                    lnB_future = np.zeros([self.n_states, 1]) # No information after selected time horizon
                else:
                    s_tau_future = np.reshape(self.post_x[:, tau + 1, this_policy], (self.n_states, 1))
                    lnB_future = np.dot(self.aip_log(self.bwd_trans_B[:, :, self.policy_indexes_v[this_policy]]), s_tau_future) 

                # Compute posterior for this policy at this time    
                s_pi_tau = self.aip_softmax(lnB_past + lnB_future + lnA)
                # Update beliefs accroding to prior and normalize.
                s_pi_tau = self.aip_norm(self._mdp.kappa_d*s_pi_tau + self._mdp.D)

                # Store the posterior expectation over states
                self.post_x[:, tau, this_policy] = np.transpose(s_pi_tau)

                # Compute F
                self.F[this_policy] = self.F[this_policy] + np.dot(self.post_x[:, tau, this_policy], self.aip_log(s_pi_tau) - lnB_past - lnA)

        # print('Free energy', self.F)
        # print('Posterior', self.post_x[:, :, :])
        return self.F, self.post_x

    def infer_policies(self):
        # Initialize expected free energy of policies
        self.G = np.zeros([self.n_policies, 1])

        # Expected free-energy calculation
        for this_policy in range(self.n_policies):
            for future_time in range(1, self.t_horizon):
                # If considering an identity mapping for the likelihood, the term diag(A.lnA).s_pi_tau is zero (ambiguity) this is always the case for us
                # Compute posterior observation considering updated posterior state and likelihood matrix
                o_pi_tau = np.argmax(np.dot(self.likelihood_A, np.transpose(self.post_x[:, future_time, this_policy])))
                self.sparse_O[0, o_pi_tau, future_time] = 1
                self.G[this_policy] = self.G[this_policy] + np.dot(self.aip_log(self.sparse_O[0, :, future_time]) - np.transpose(self._mdp.C), self.sparse_O[0, :, future_time])

        # Policy posterior
        post_pi = self.aip_softmax(self._mdp.E - self.F - self.G)
        self.u = np.argmax(self.aip_softmax(self.aip_log(post_pi)))
        
        # print('Selected action', self.u)

        # Bayesian model averaging of hidden states (over policies). This only influences the posterior estimates for future states, not current ones
        # Reset variable for Bayesian model average posterior over policies and time horizon
        self.post_x_bma = np.zeros([self.n_states, self.t_horizon])
        for time in range(self.t_horizon):
            for policy in range(self.n_policies):
                self.post_x_bma[:, time] = self.post_x_bma[:, time] + self.post_x[:, time, policy]*post_pi[policy]

        # Update initial state to keep track for the next iteration
        self._mdp.D = self.post_x_bma[:, 0].reshape(3, 1)  # Take first policy (idle) at current time, so simple state update

        return self.G, self.u
        
    def aip_log(self, var):
        # Natural logarithm of an element, preventing 0. The element can be a scalar, vector or matrix
        return np.log(var + 1e-16)

    def aip_norm(self, var):
        # Normalisation of probability matrix (column elements sum to 1)
        # The function goes column by column and it normalise such that the
        # elements of each column sum to 1
        # In case of a matrix
        for column_id in range(np.shape(var)[1]):  # Loop over the number of columns
            sum_column = np.sum(var[:, column_id])
            if sum_column > 0:
                var[:, column_id] = var[:, column_id] / sum_column  # Divide by the sum of the column
            else:
                var[:, column_id] = 1 / np.shape(var)[0]  # Divide by the number of rows
        return var

    def aip_softmax(self, var):
        # Function to compute the softmax of a given column array: sigma = exp(x) / sum(exp(x))
        ex = np.exp(var)  # Compute exponential
        for i in range(np.shape(var)[0]):
            var[i] = ex[i] / np.sum(ex)  # Compute softmax element by element
        return var
    
    # Update observations for an agent
    def set_observation(self, obs):
        self._mdp.o = obs
    
    # Update the preferences of the agent over the states it cares about
    def set_preferences(self, pref):
        self._mdp.C = pref

    # Get current action
    def get_action(self):
        return self._mdp.u

    # Get current best estimate of the state
    def get_current_state(self):
        return self._mdp.D

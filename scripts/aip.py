# This is a module to perform active inference.
import numpy as np
import copy

def aip_log(var):
    # Natural logarithm of an element, preventing 0. The element can be a scalar, vector or matrix
    return np.log(var + 1e-16)


def aip_norm(var):
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


def aip_softmax(var):
    # Function to compute the softmax of a given column array: sigma = exp(x) / sum(exp(x))
    ex = np.exp(var)  # Compute exponential
    for i in range(np.shape(var)[0]):
        var[i] = ex[i] / np.sum(ex)  # Compute softmax element by element
    return var

##TODO here I need to add a process for the state stimation and then call the one for action selection. Basically run the action selection twice where the second time you remove the observation

def aip_select_action(mdp):
    # The core function which performs free-energy minimisation and action selection
    # mdp is a structure with several fields
    # ------------------------------------------------------------------------------------------------------------------

    # Initialization of variables
    n_policies = np.shape(mdp.V)[0]  # Number of allowable policies
    n_states = np.shape(mdp.B)[0]  # Number of states
    n_actions = np.shape(mdp.B)[2]  # Number of controls
    n_outcomes = n_states  # Number of sensory inputs, same as the states
    n_iter = 4  # Varitional bayes iterations
    t_horizon = 2  # Time horizon to look one step ahead

    # Assigning local variables to this instance of the function
    # ------------------------------------------------------------------------------------------------------------------
    policy_indexes_v = mdp.V  # Indexes of possible policies
    policy_post_u = np.zeros([n_policies, t_horizon])  # Initialize vector to contain posterior probabilities of actions

    # Prior expectation over hidden states at the beginning of the trial
    if hasattr(mdp, 'd'):
        prior_D = aip_norm(mdp.d)
    elif hasattr(mdp, 'D'):
        prior_D = aip_norm(mdp.D)
    else:
        prior_D = aip_norm(np.ones((n_states, 1)))

    # Likelihood matrix
    likelihood_A = aip_norm(mdp.A)

    # Transition matrix
    fwd_trans_B = np.zeros((n_states, n_states, n_actions))
    bwd_trans_B = np.zeros((n_states, n_states, n_actions))

    for action in range(n_actions):
        # Retrieve forward messages, B
        fwd_trans_B[:, :, action] = aip_norm(mdp.B[:, :, action])
        # Retrieve backward messages, transpose of B
        bwd_trans_B[:, :, action] = np.transpose(aip_norm(mdp.B[:, :, action]))

    # Prior preferences (log probabilities) : C
    prior_C = aip_log(aip_softmax(copy.copy(mdp.C)))
    # Preferences over policies
    prior_E = aip_log(aip_norm(mdp.E))

    # Current observation
    # ------------------------------------------------------------------------------------------------------------------
    outcome_o = np.zeros([1, t_horizon]) - 1
    # If outcomes have been specified then set it, otherwise leave to 0
    if hasattr(mdp, 'o'):
        outcome_o[0, 0] = mdp.o  # Outcomes here are indicated in 'compact notation' with 1 and 2
    # Putting observations in sparse form, initialization
    sparse_O = np.zeros((1, n_states, n_outcomes))  # Outcomes here are indicated as [1 0], [0 1]

    # Posterior states
    # ------------------------------------------------------------------------------------------------------------------
    # Initial guess about posterior hidden states, in 'compact notation' with 1 and 2
    hidden_states_s = np.zeros([1, t_horizon]) - 1  # Unassigned states and values are -1
    hidden_states_s[0, 0] = np.argmax(mdp.D)  # Get index of max value and set as initial state

    # Initialize posterior expectation over hidden states
    post_x = np.zeros([n_states, t_horizon, n_policies]) + 1 / n_states
    sparse_post_X = np.zeros([n_states, t_horizon])
    sparse_post_X[:, 0] = np.transpose(prior_D)
    # Set the current state to what contained in D. At the next step it is still uncertain, so we leave it as that
    for policy in range(n_policies):
        post_x[:, 0, policy] = np.transpose(prior_D)

    # Active inference loop
    # ------------------------------------------------------------------------------------------------------------------
    for t in range(t_horizon):

        # Initialization of this trial, hidden states, outcomes, and free-energy
        # ======================================================================
        # Sample state, if not specified. The next state is generated by action
        if hidden_states_s[0, t] == -1:  # This is equivalent to s+1 = B*s
            # This is equivalent to s+1=B*s
            hidden_states_s[0, t] = np.argmax(fwd_trans_B[:, int(hidden_states_s[0, t - 1]), int(mdp.u[0, t - 1])])

        # If outcome is not specified, sample
        if outcome_o[0, t] == -1:
            # Sample from likelihood given hidden state. This is equivalent to o = A*s
            outcome_o[0, t] = np.argmax(likelihood_A[:, int(hidden_states_s[0, t])])
        # Put it in sparse form: convert scalar index to a "1" in the  corresponding place
        sparse_O[0, int(outcome_o[0, t]), t] = 1

        # Initialize free-energy for each policy
        free_energy = np.zeros([n_policies, 1])

        # Variational updates (hidden states) under sequential policies (equations from mathematical derivation)
        # ======================================================================================================
        for this_policy in range(n_policies):  # Loop over the available policies
            for bayes_iter in range(n_iter):  # Iterate belief updates
                #  Main loop for free-energy calculation and state estimation
                free_energy[this_policy] = 0  # Reset free energy for this policy
                for time_tau in range(t_horizon):  # Loop over future time points
                    # Hidden states for this time and policy
                    s_pi_tau = post_x[:, time_tau, this_policy]
                    s_pi_tau = np.reshape(s_pi_tau, (n_states, 1))

                    # Support variables from SPM
                    qL = np.zeros([n_states, 1])

                    # Marginal likelihood over outcomes
                    if time_tau <= t:
                        # Is there a log here or not?
                        qL = np.dot(aip_log(likelihood_A), np.transpose(sparse_O[:, :, time_tau]))

                        # Entropy
                    qx = aip_log(s_pi_tau)

                    # Empirical priors
                    if time_tau == 0:  # (Backward messages)
                        # Reshape to correct column form
                        dummy_post_x = np.reshape(post_x[:, time_tau + 1, this_policy], (n_states, 1))
                        px = aip_log(prior_D) \
                             + np.dot(aip_log(bwd_trans_B[:, :, policy_indexes_v[this_policy]]), dummy_post_x)
                        vF = px + qL - qx
                    else:  # (Forward messages)
                        # Reshape to correct column form
                        dummy_post_x = np.reshape(post_x[:, time_tau - 1, this_policy], (n_states, 1))
                        px = np.dot(aip_log(fwd_trans_B[:, :, policy_indexes_v[this_policy]]), dummy_post_x)
                        vF = px + qL - qx

                    # Auxiliary variables for gradient of F
                    if time_tau == 0:   # (Backward messages)
                        FF = -qx + aip_log(prior_D) - qL
                    else:  # (Forward messages)
                        dummy_post_x = np.reshape(post_x[:, time_tau - 1, this_policy], (n_states, 1))
                        FF = -qx + np.dot(aip_log(fwd_trans_B[:, :, policy_indexes_v[this_policy]]), dummy_post_x) - qL

                    # Negative Free-energy
                    free_energy[this_policy] = free_energy[this_policy] + np.dot(np.transpose(s_pi_tau), FF)
                    # State update
                    s_pi_tau = aip_softmax(qx + vF)

                    # Store the posterior expectation over states
                    post_x[:, time_tau, this_policy] = np.transpose(s_pi_tau)

        # Expected free-energy and action selection
        # =========================================
        # Initialize expected free energy of policies
        expected_F = np.zeros([n_policies, 1])

        for this_policy in range(n_policies):
            for future_time in range(t, t_horizon):
                dummy_post_x = np.reshape(post_x[:, future_time, this_policy], (n_states, 1))
                qo = np.dot(likelihood_A, dummy_post_x)
                expected_F[this_policy] = expected_F[this_policy] \
                                          + np.dot(np.transpose(qo), (prior_C - aip_log(qo)))

        # Variational updates of policies
        # =========================================
        qu = aip_softmax(prior_E + expected_F + free_energy)
        policy_post_u[:, t] = np.reshape(qu, (n_policies,))   # Every column of u indicates the posterior about a policy

        # Bayesian model averaging of hidden states (over policies)
        for i in range(t_horizon):
            # Reshape puts the cells of x for each of the allowable policies as a column for X. Then,
            # we multiply for u, to obtain the policy independent state estimation
            sparse_post_X[:, i] = np.transpose(np.reshape(np.dot(np.reshape(post_x[:, i, :], (n_states, n_policies)), policy_post_u[:, t]), (n_states, 1)))

        # Record (negative) free energies
        if hasattr(mdp, 'F'):
            # Note that F is the total (accumulated) free-energy after t time steps according to a policy
            mdp.F[:, t] = np.reshape(free_energy, (n_policies,))
        else:
            setattr(mdp, 'F', np.zeros([n_policies, t_horizon]))
            mdp.F[:, t] = np.reshape(free_energy, (n_policies,))

        if hasattr(mdp, 'G'):
            mdp.G[:, t] = np.reshape(expected_F, (n_policies,))
        else:
            setattr(mdp, 'G', np.zeros([n_policies, t_horizon]))
            mdp.G[:, t] = np.reshape(expected_F, (n_policies,))

        # Action selection
        if t < t_horizon-1:
            # Marginal posterior over actions
            Pu = aip_softmax(aip_log(policy_post_u[:, t]))
            if hasattr(mdp, 'u'):
                mdp.u[0, t] = np.argmax(Pu)        # Choose the most probable posterior action
            else:
                setattr(mdp, 'u', np.zeros([1, t_horizon-1]))
                mdp.u[0, t] = np.argmax(Pu)

    # Learning
    # ------------------------------------------------------------------------------------------------------------------
    # Update of initial belief d
    if hasattr(mdp, 'd'):
        mdp.d = mdp.d + np.reshape(mdp.kappa_d * sparse_post_X[:, 0], (n_states, 1))  # Update initial belief
        # Normalize probability
        mdp.d = aip_norm(mdp.d)
        # Re-set initial state
        mdp.D = mdp.d
        mdp.s = np.argmax(mdp.d)  # Update most probable state
    else:
        mdp.s = np.argmax(mdp.D)

    return mdp  # Updated model which contains state estimation an policy selection

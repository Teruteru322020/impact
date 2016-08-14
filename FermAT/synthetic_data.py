from scipy.integrate import odeint
import numpy as np
import matplotlib.pyplot as plt


def generate_data(y0, t, model, biomass_keys, substrate_keys, product_keys, noise=0, plot=True):
    """
    Generates synthetic data

    Parameters
    ----------
    y0 : list
        Starting values
    t : array
        Time vector
    model: cobraPy model
        Optimized cobraPy model
    biomass_keys: list
        A list with the a string of the biomass name
    substrate_keys: list
        A list with the a string of the susbstrate name
    product_keys: list
        A list of strings of product names
    noise: float, optional
        If you'd like to add some noise to parameters
    plot : bool, optional
        Flag for plotting data

    Returns
    -------
    dFBA_profile: dict
        Returns a dict with time profiles for each product, substrate and biomass
    """""

    # Let's assign the data to these variables
    biomass_flux = []
    biomass_flux.append(model.solution.x_dict[biomass_keys[0]])

    substrate_flux = []
    substrate_flux.append(model.solution.x_dict[substrate_keys[0]])

    product_flux = [model.solution.x_dict[key] for key in product_keys]

    exchange_keys = biomass_keys + substrate_keys + product_keys

    # Now, let's build our model for the dFBA
    def dFBA_functions(y, t, biomass_flux, substrate_flux, product_flux):
        # Append biomass, substrate and products in one list
        exchange_reactions = biomass_flux + substrate_flux + product_flux
        # y[0]           y[1]
        dydt = []
        for exchange_reaction in exchange_reactions:
            if y[1] > 0:  # If there is substrate
                dydt.append(exchange_reaction * y[0])
            else:  # If there is not substrate
                dydt.append(0)
        return dydt

    # Now let's generate the data
    sol = odeint(dFBA_functions, y0, t, args=([flux * np.random.uniform(1 - noise, 1 + noise) for flux in biomass_flux],
                                              [flux * np.random.uniform(1 - noise, 1 + noise) for flux in
                                               substrate_flux],
                                              [flux * np.random.uniform(1 - noise, 1 + noise) for flux in
                                               product_flux]))

    dFBA_profile = {key: [row[i] for row in sol] for i, key in enumerate(exchange_keys)}

    if plot:
        plt.figure(figsize=[12, 6])
        for key in exchange_keys:
            plt.plot(t, dFBA_profile[key])
        # plt.ylim([0, 250])
        plt.legend(exchange_keys, loc=2)

    return dFBA_profile
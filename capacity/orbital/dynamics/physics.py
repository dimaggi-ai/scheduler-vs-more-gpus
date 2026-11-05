"""Exact constant-input battery and linear lumped thermal models; explicit units."""
import math
from .contracts import finite


def temperature(initial, sink, heat_w, conductance, capacity, seconds):
    if conductance == 0:
        result = initial + heat_w * seconds / capacity
    else:
        equilibrium = sink + heat_w / conductance
        x = conductance * seconds / capacity
        finite(equilibrium,x)
        result = initial + (equilibrium-initial) * -math.expm1(-x)
    finite(result)
    return result


def thermal_crossing(initial, limit, sink, heat_w, conductance, capacity):
    """Seconds to upper threshold when heating; infinity if never crossed."""
    if conductance == 0:
        return math.inf if heat_w == 0 else (limit-initial)*capacity/heat_w
    equilibrium = sink + heat_w/conductance
    finite(equilibrium)
    if equilibrium <= limit or equilibrium <= initial:
        return math.inf
    ratio = (limit-initial)/(equilibrium-initial)
    result = -capacity/conductance*math.log1p(-ratio)
    finite(result)
    return max(0.0,result)


def battery(initial, solar_kw, load_kw, config, seconds):
    """kWh ledger including conversion losses and curtailment, no hidden recharge."""
    solar = solar_kw*seconds/3600
    load = load_kw*seconds/3600
    net = solar_kw-load_kw
    if net >= 0:
        incoming_kw = min(net,config['max_charge_kw'])
        stored = min(config['capacity_kwh']-initial,
                     incoming_kw*config['charge_efficiency']*seconds/3600)
        received = stored/config['charge_efficiency']
        loss = received-stored
        curtailed = max(0.0, solar-load-received)
        final = initial+stored
    else:
        withdrawn = -net*seconds/3600/config['discharge_efficiency']
        loss = withdrawn + net*seconds/3600
        curtailed = 0.0
        final = initial-withdrawn
    residual = initial+solar-load-loss-curtailed-final
    finite(solar,load,loss,curtailed,final,residual)
    tolerance = 1e-10*max(1,abs(initial),abs(final),solar,load)
    if abs(residual)>tolerance:
        raise ValueError('energy conservation failure')
    return dict(initial_kwh=initial,final_kwh=final,solar_kwh=solar,load_kwh=load,
                conversion_loss_kwh=loss,curtailed_kwh=curtailed,
                residual_kwh=residual,residual_tolerance_kwh=tolerance)

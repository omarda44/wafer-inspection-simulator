import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Button, RadioButtons, TextBox


# ============================================================
# CONSTANTS
# ============================================================

WAFER_DIAMETER_MM = 300

# Used only to normalize the optical signal.
# 80 nm defect at 355 nm -> normalized signal = 1 a.u.
REFERENCE_SIZE_NM = 80
REFERENCE_WAVELENGTH_NM = 355

# Negative-Binomial clustering parameters.
# Smaller alpha -> stronger clustering.
# These are representative simulation values, not universal fab constants.
CLUSTER_ALPHA = {
    "Random particles": 20.0,          # Nearly Poisson / random
    "Contamination cluster": 2.0,      # Clustered defects
    "Scratch": 0.5,                    # Strong spatial concentration
    "Edge ring": 1.0,                  # Strong edge concentration
}


# ============================================================
# DEFECT MAP
# ============================================================

def defect_positions(pattern, count, radius, rng):
    """Generate defect locations according to the selected wafer-map pattern."""

    if pattern == "Random particles":
        # sqrt() gives uniform distribution over the circular AREA.
        angle = rng.uniform(0, 2 * np.pi, count)
        distance = radius * np.sqrt(rng.random(count))

    elif pattern == "Contamination cluster":
        # Two local contamination regions.
        centers = np.array([[-0.35, 0.25], [0.30, -0.20]]) * radius
        points = centers[rng.integers(0, len(centers), count)]
        points += rng.normal(0, 0.10 * radius, (count, 2))

        # Keep defects inside the wafer.
        distance = np.hypot(points[:, 0], points[:, 1])
        outside = distance > radius
        points[outside] *= (0.98 * radius / distance[outside])[:, None]

        return points[:, 0], points[:, 1]

    elif pattern == "Scratch":
        # Line-shaped signature: can indicate handling or CMP problem.
        x = np.linspace(-0.8 * radius, 0.8 * radius, count)
        y = 0.35 * x + rng.normal(0, 0.015 * radius, count)
        return x, y

    else:  # Edge ring
        # Defects concentrated near the wafer edge.
        angle = rng.uniform(0, 2 * np.pi, count)
        distance = rng.normal(0.88 * radius, 0.025 * radius, count)

    return distance * np.cos(angle), distance * np.sin(angle)


# ============================================================
# YIELD MODEL
# ============================================================

def negative_binomial_yield(defect_density, critical_area, alpha):
    """
    Negative-Binomial defect-limited yield:

        Y = (1 + Ac*D0/alpha)^(-alpha)

    D0    = killer-defect density [defects/cm²]
    Ac    = critical area [cm²]
    alpha = clustering parameter

    Large alpha approaches the Poisson model:
        Y = exp(-Ac*D0)
    """
    return (1 + critical_area * defect_density / alpha) ** (-alpha)


# ============================================================
# INSPECTION
# ============================================================

def inspect_wafer(pattern, count, mean_size, wavelength,
                  haze, base_threshold, critical_area, rng):
    """Simulate dark-field inspection and calculate defect-limited yield."""

    radius = WAFER_DIAMETER_MM / 2

    # 1. Generate defect positions.
    x, y = defect_positions(pattern, count, radius, rng)

    # 2. Generate different defect sizes around the selected mean.
    # Log-normal distribution is only a simulation assumption.
    size = rng.lognormal(np.log(mean_size), 0.25, count)

    # 3. Rayleigh scattering:
    # signal proportional to d^6 / lambda^4.
    ideal_signal = (
        (size / REFERENCE_SIZE_NM) ** 6
        * (REFERENCE_WAVELENGTH_NM / wavelength) ** 4
    )

    # 4. Haze = background scattering caused mainly by surface roughness.
    measured_signal = np.maximum(
        ideal_signal + rng.normal(0, haze, count),
        1e-3
    )

    # 5. Detection threshold.
    # 3*Haze is a simplified simulation assumption.
    threshold = base_threshold + 3 * haze
    detected = measured_signal >= threshold

    # 6. Wafer area in cm².
    # 300 mm diameter -> 15 cm radius.
    wafer_area_cm2 = np.pi * (WAFER_DIAMETER_MM / 20) ** 2

    # We assume generated defects are already killer defects D0.
    true_density = count / wafer_area_cm2
    measured_density = detected.sum() / wafer_area_cm2

    # Alpha is selected internally according to defect pattern.
    alpha = CLUSTER_ALPHA[pattern]

    # 7. Yield based on all generated defects.
    model_yield = negative_binomial_yield(
        true_density,
        critical_area,
        alpha
    )

    # Yield estimated only from defects found by inspection.
    estimated_yield = negative_binomial_yield(
        measured_density,
        critical_area,
        alpha
    )

    return (
        x, y, size, measured_signal, threshold, detected,
        model_yield, estimated_yield,
        true_density, measured_density
    )


# ============================================================
# WAFER DRAWING
# ============================================================

def draw_wafer(ax, title):
    """Draw one circular 300-mm wafer."""

    radius = WAFER_DIAMETER_MM / 2
    ax.clear()

    ax.add_patch(
        Circle(
            (0, 0),
            radius,
            facecolor="#f4f7fa",
            edgecolor="#172b4d",
            lw=2
        )
    )

    ax.set(
        xlim=(-160, 160),
        ylim=(-160, 160),
        aspect="equal",
        xlabel="x [mm]",
        ylabel="y [mm]",
        title=title
    )

    ax.grid(alpha=0.18)


# ============================================================
# RUN BUTTON
# ============================================================

def run_inspection(_=None):
    """Read user inputs, run the simulation, and update all graphs."""

    try:
        count = int(inputs["Defects"].text)
        mean_size = float(inputs["Mean size [nm]"].text)
        wavelength = float(inputs["Wavelength [nm]"].text)
        haze = float(inputs["Haze [a.u.]"].text)
        base_threshold = float(inputs["Base threshold"].text)
        critical_area = float(inputs["Critical area [cm2]"].text)

        if (
            min(count, mean_size, wavelength, critical_area) <= 0
            or min(haze, base_threshold) < 0
        ):
            raise ValueError

    except ValueError:
        status.set_text("Enter valid positive values; Haze may be zero.")
        fig.canvas.draw_idle()
        return

    pattern = pattern_selector.value_selected

    result = inspect_wafer(
        pattern,
        count,
        mean_size,
        wavelength,
        haze,
        base_threshold,
        critical_area,
        np.random.default_rng()
    )

    (
        x, y, size, signal, threshold, detected,
        model_yield, estimated_yield,
        true_density, measured_density
    ) = result

    # Marker size is only visual, not physical scale.
    marker_size = 12 + 28 * (size / mean_size) ** 2

    # --------------------------------------------------------
    # GRAPH 1: All defects that actually exist
    # --------------------------------------------------------
    draw_wafer(ax_true, "Generated defects")

    ax_true.scatter(
        x, y,
        s=marker_size,
        c="#268bd2",
        alpha=0.75
    )

    # --------------------------------------------------------
    # GRAPH 2: Detected and missed defects
    # --------------------------------------------------------
    draw_wafer(ax_result, "Inspection result")

    ax_result.scatter(
        x[~detected],
        y[~detected],
        s=marker_size[~detected],
        c="#a7adb4",
        marker="x",
        label="Missed"
    )

    ax_result.scatter(
        x[detected],
        y[detected],
        s=marker_size[detected],
        c="#d62728",
        edgecolors="white",
        label="Detected"
    )

    ax_result.legend(loc="upper right")

    # --------------------------------------------------------
    # GRAPH 3: Dark-field scattering signal
    # --------------------------------------------------------
    ax_signal.clear()

    colors = np.where(
        detected,
        "#d62728",
        "#a7adb4"
    )

    ax_signal.scatter(
        size,
        signal,
        c=colors,
        alpha=0.75
    )

    size_line = np.linspace(
        max(1, size.min()),
        size.max(),
        200
    )

    ideal_line = (
        (size_line / REFERENCE_SIZE_NM) ** 6
        * (REFERENCE_WAVELENGTH_NM / wavelength) ** 4
    )

    ax_signal.plot(
        size_line,
        ideal_line,
        color="#268bd2",
        label=r"$d^6/\lambda^4$ model"
    )

    # Above threshold -> detected.
    # Below threshold -> missed.
    ax_signal.axhline(
        threshold,
        color="black",
        ls="--",
        label="Detection threshold"
    )

    ax_signal.set(
        xlabel="Defect size [nm]",
        ylabel="Measured scattering [a.u.]",
        title="Dark-field signal"
    )

    # Log scale because d^6 creates a large signal range.
    ax_signal.set_yscale("log")
    ax_signal.grid(alpha=0.2)
    ax_signal.legend()

    # --------------------------------------------------------
    # FINAL RESULTS
    # --------------------------------------------------------
    found = int(detected.sum())
    capture = 100 * found / count

    status.set_text(
        f"Pattern: {pattern}   |   "
        f"Detected: {found}/{count} ({capture:.1f}%)   |   "
        f"D0 actual: {true_density:.4f}/cm2   |   "
        f"D0 measured: {measured_density:.4f}/cm2   |   "
        f"Model yield: {100 * model_yield:.1f}%   |   "
        f"Inspection estimate: {100 * estimated_yield:.1f}%"
    )

    fig.canvas.draw_idle()


# ============================================================
# USER INTERFACE
# ============================================================

# Three views:
# 1. Generated defects
# 2. Inspection result
# 3. Optical scattering signal
fig, (ax_true, ax_result, ax_signal) = plt.subplots(
    1, 3, figsize=(15, 7)
)

fig.subplots_adjust(
    left=0.245,
    right=0.98,
    bottom=0.12,
    top=0.88,
    wspace=0.35
)

fig.suptitle(
    "Wafer Dark-Field Inspection Simulation",
    fontsize=16,
    fontweight="bold"
)


# Parameters that can be changed live.
defaults = {
    "Defects": "60",
    "Mean size [nm]": "100",
    "Wavelength [nm]": "355",
    "Haze [a.u.]": "0.10",
    "Base threshold": "1.0",
    "Critical area [cm2]": "0.5",
}

inputs = {}

for y, (label, value) in zip(
    np.linspace(0.82, 0.47, len(defaults)),
    defaults.items()
):
    inputs[label] = TextBox(
        fig.add_axes([0.115, y, 0.075, 0.045]),
        label,
        initial=value
    )


fig.text(
    0.02,
    0.40,
    "Defect pattern",
    weight="bold"
)

pattern_selector = RadioButtons(
    fig.add_axes([0.025, 0.19, 0.17, 0.19]),
    (
        "Random particles",
        "Contamination cluster",
        "Scratch",
        "Edge ring"
    ),
)


run_button = Button(
    fig.add_axes([0.045, 0.105, 0.13, 0.055]),
    "Run inspection"
)

run_button.on_clicked(run_inspection)

status = fig.text(
    0.245,
    0.04,
    "",
    fontsize=9
)

# Run once when the program opens.
run_inspection()

plt.show()
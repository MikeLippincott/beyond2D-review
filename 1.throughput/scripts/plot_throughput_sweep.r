library(ggplot2)
library(dplyr)
library(readr)
library(scales)
library(patchwork)
library(scatterplot3d)
library(gridGraphics)  # lets patchwork place a base graphics plot

# all cleaning is done in calculate_throughput_metrics.ipynb
dimension_levels <- c("XY", "XYZ", "XYT", "XYZT")
read_results <- function(file) {
  read_csv(file.path("../results", file), show_col_types = FALSE) %>%
    mutate(z_steps = factor(z_steps))
}
series <- read_results("throughput_series.csv") %>% mutate(dimensions = factor(dimensions, levels = dimension_levels))
points <- read_results("throughput_feasibility.csv") %>% mutate(z_num = as.numeric(as.character(z_steps)))
feasibility_z_samples <- read_results("throughput_feasibility_z_samples.csv") %>% mutate(z_num = as.numeric(as.character(z_steps)))
feasibility_samples_interval <- read_results("throughput_feasibility_samples_interval.csv") %>% mutate(z_num = as.numeric(as.character(z_steps)))
interval_levels <- sort(unique(points$interval_h))
series <- mutate(series, interval = factor(interval_h, levels = interval_levels, labels = round(interval_levels, 2)))
dir.create("../figures", showWarnings = FALSE)
base_size <- 30  # text size of every plot
# Okabe-Ito colour-blind safe palette (yellow swapped for grey so it shows on white)
palette <- c("#E69F00", "#56B4E9", "#009E73", "#0072B2", "#D55E00", "#CC79A7", "#999999", "#000000")
# second variable is drawn as point shape on solid lines, which reads better than dashes
shapes <- c(16, 17, 15, 18, 4, 3, 8, 1, 2, 0, 5, 6, 7, 9, 10, 11, 12, 13, 14, 25)  # enough for up to 20 levels


# without a time dimension (XY, XYZ) one pass is acquired whatever the interval is, so
# those facets hold a single point per z step; the interval has a meaning, and a shape,
# only in the facets that have T
with_time <- filter(series, grepl("T", dimensions))
static <- filter(series, !grepl("T", dimensions))

p3 <- ggplot(mapping = aes(total_time_h, data_TB, colour = z_steps)) +
  geom_line(data = with_time, aes(group = interaction(z_steps, interval))) +
  geom_point(data = with_time, aes(shape = interval), size = 7) +
  geom_point(data = static, shape = 16, size = 7) +
  facet_wrap(~dimensions, nrow = 2, ncol = 2) +
  scale_x_log10(breaks = sort(unique(series$total_time_h))) +
  scale_y_log10(labels = label_comma()) +
  scale_colour_manual(values = palette, drop = FALSE) +
  scale_shape_manual(values = shapes, drop = FALSE) +
  labs(x = "total time (h)", y = "data volume (TB)", colour = "z steps", shape = "interval (h)") +
  guides(x = guide_axis(angle = 45)) +
  theme_bw(base_size = base_size)
ggsave("../figures/data_vs_time.png", p3, width = 16, height = 14, dpi = 200)
p3

# time per pass is linear in z steps: pass = a + b * z, so one pass fits in the
# interval when z <= (interval - a) / b
pass_fit <- coef(lm(time_per_plate_s ~ z_num, data = points))
z_limits <- range(points$z_num) * c(0.7, 1.4)
boundary <- tibble(interval_h = exp(seq(log(min(points$interval_h)), log(max(points$interval_h)), length.out = 300))) %>%
  mutate(z_edge = (interval_h * 3600 - pass_fit[[1]]) / pass_fit[[2]],
         z_edge = pmin(pmax(z_edge, z_limits[1]), z_limits[2]))

p5 <- ggplot() +
  geom_ribbon(data = boundary, aes(interval_h, ymin = z_limits[1], ymax = z_edge, fill = "possible"), alpha = 0.12) +
  geom_ribbon(data = boundary, aes(interval_h, ymin = z_edge, ymax = z_limits[2], fill = "not possible"), alpha = 0.12) +
  geom_line(data = boundary, aes(interval_h, z_edge), linewidth = 1.5) +
  geom_point(data = points, aes(interval_h, z_num, colour = log_ratio), size = 14) +
  scale_x_log10(breaks = interval_levels, labels = label_number(accuracy = 0.01, drop0trailing = TRUE),
                expand = expansion(0)) +
  scale_y_log10(breaks = sort(unique(points$z_num)), expand = expansion(0)) +
  coord_cartesian(ylim = z_limits) +
  scale_fill_manual(values = c(possible = "#009E73", "not possible" = "#D55E00"), name = NULL) +
  # shaded on log10(pass time / interval): 0 is exactly one pass per interval
  scale_colour_gradient2(low = "#009E73", mid = "grey90", high = "#D55E00", midpoint = 0,
                         breaks = log10(c(0.1, 1, 10, 100)), labels = c("0.1", "1", "10", "100"),
                         name = "pass time /\ninterval") +
  labs(x = "interval (h)", y = "z steps") +
  guides(x = guide_axis(angle = 45), colour = guide_colourbar(barheight = 10)) +
  theme_bw(base_size = base_size)
ggsave("../figures/steps_vs_interval.png", p5, width = 16, height = 10, dpi = 200)
p5

# one pass takes samples x (a + b * z) seconds, with the time per sample linear in z steps
per_sample <- distinct(feasibility_z_samples, z_num, samples, time_per_plate_s) %>%
  mutate(time_per_sample_s = time_per_plate_s / samples)
sample_fit <- coef(lm(time_per_sample_s ~ z_num, data = per_sample))
fixed_z <- as.numeric(as.character(feasibility_samples_interval$z_steps[1]))
fixed_interval_h <- feasibility_z_samples$interval_h[1]
log_seq <- function(x, n = 300) exp(seq(log(min(x)), log(max(x)), length.out = n))

feasibility_panel <- function(points, boundary, x, y, ymin, ymax, x_breaks, x_lab, y_lab, x_labels = label_comma(), y_breaks = sort(unique(points[[y]])), y_labels = label_comma(),
                              possible_below = TRUE) {
  below <- if (possible_below) "possible" else "not possible"
  above <- if (possible_below) "not possible" else "possible"
  ggplot() +
    geom_ribbon(data = boundary, aes(.data[[x]], ymin = ymin, ymax = edge, fill = below), alpha = 0.12) +
    geom_ribbon(data = boundary, aes(.data[[x]], ymin = edge, ymax = ymax, fill = above), alpha = 0.12) +
    geom_line(data = boundary, aes(.data[[x]], edge), linewidth = 1.5) +
    geom_point(data = points, aes(.data[[x]], .data[[y]], colour = log_ratio), size = 12) +
    scale_x_log10(breaks = x_breaks, labels = x_labels, expand = expansion(0)) +
    scale_y_log10(breaks = y_breaks, labels = y_labels, expand = expansion(0)) +
    coord_cartesian(ylim = c(ymin, ymax)) +
    scale_fill_manual(values = c(possible = "#009E73", "not possible" = "#D55E00"), name = NULL) +
    scale_colour_gradient2(low = "#009E73", mid = "grey90", high = "#D55E00", midpoint = 0,
                           breaks = log10(c(0.1, 1, 10, 100)), labels = c("0.1", "1", "10", "100"),
                           name = "pass time /\ninterval") +
    labs(x = x_lab, y = y_lab) +
    guides(x = guide_axis(angle = 45), colour = guide_colourbar(barheight = 10)) +
    theme_bw(base_size = base_size)
}

# z steps vs samples: a pass fits when z <= (interval / samples - a) / b
z_limits <- range(feasibility_z_samples$z_num) * c(0.7, 1.4)
z_boundary <- tibble(samples = log_seq(feasibility_z_samples$samples)) %>%
  mutate(edge = pmin(pmax((fixed_interval_h * 3600 / samples - sample_fit[[1]]) / sample_fit[[2]], z_limits[1]), z_limits[2]))
p_zs <- feasibility_panel(feasibility_z_samples, z_boundary, "samples", "z_num", z_limits[1], z_limits[2],
                          sort(unique(feasibility_z_samples$samples)), "samples (wells x FOVs)", "z steps")

# interval vs samples: a pass fits when interval >= samples * (a + b * z)
interval_limits <- range(feasibility_samples_interval$interval_h) * c(0.7, 1.4)
interval_boundary <- tibble(samples = log_seq(feasibility_samples_interval$samples)) %>%
  mutate(edge = pmin(pmax(samples * (sample_fit[[1]] + sample_fit[[2]] * fixed_z) / 3600, interval_limits[1]), interval_limits[2]))
p_si <- feasibility_panel(feasibility_samples_interval, interval_boundary, "samples", "interval_h", interval_limits[1], interval_limits[2],
                          sort(unique(feasibility_samples_interval$samples)), "samples (wells x FOVs)", "interval (h)",
                          y_breaks = interval_levels, y_labels = label_number(accuracy = 0.01, drop0trailing = TRUE),
                          possible_below = FALSE)

p8 <- p_zs / p_si + plot_layout(guides = "collect")
ggsave("../figures/samples_feasibility.png", p8, width = 16, height = 22, dpi = 200)
p8

# one pass takes samples x (a + b * z) seconds, so the most z steps that fit in an interval is
# (interval / samples - a) / b; 0 where not even a single z step fits
z_top <- max(feasibility_z_samples$z_num)
# the surface is flat once a pass fits at every sample count, which is by 8 h, so the axis stops at 12 h
interval_grid <- seq(min(points$interval_h), 12, length.out = 60)
samples_grid <- seq(min(feasibility_z_samples$samples), max(feasibility_z_samples$samples), length.out = 60)
max_z <- outer(interval_grid, samples_grid, function(i, s) (i * 3600 / s - sample_fit[[1]]) / sample_fit[[2]])
max_z <- pmin(pmax(max_z, 0), z_top)

# shade each surface cell by the mean height of its four corners
n <- length(interval_grid)
cell_z <- (max_z[-n, -n] + max_z[-1, -n] + max_z[-n, -n] + max_z[-1, -1]) / 4
ramp <- scales::pal_gradient_n(c("#D55E00", "grey90", "#009E73"))
cell_colour <- ramp(cell_z / z_top)

draw_3d <- function() {
  par(mar = c(0, 6, 0, 0), cex = 2)
  persp(interval_grid, samples_grid, max_z, zlim = c(0, z_top), theta = -55, phi = 32, expand = 1.0,
        col = cell_colour, border = "grey60", lwd = 0.3, ticktype = "detailed", nticks = 5, cex.axis = 1.7, cex.lab = 2.2,
        xlab = "interval (h)", ylab = "samples", zlab = "max z steps")
  legend("topleft", inset = c(0, -0.02), legend = c(paste(z_top, "z steps fit"), "half fit", "none fit"), pch = 15, pt.cex = 2.2, cex = 1.4,
         col = c("#009E73", "grey90", "#D55E00"), bty = "n")
}
p9 <- wrap_elements(full = ~ draw_3d())
ggsave("../figures/possible_z_steps_3d.png", p9, width = 16, height = 14, dpi = 200)
p9

capacity <- read_csv("../results/throughput_capacity.csv", show_col_types = FALSE) %>%
  mutate(dimensions = factor(dimensions, levels = dimension_levels))
max_plates <- capacity %>%
  distinct(fovs_per_well, wells_per_plate, max_plates) %>%
  mutate(fovs = factor(fovs_per_well, labels = paste(sort(unique(fovs_per_well)), "FOVs per well")))
capacity <- mutate(capacity, fovs = factor(fovs_per_well, labels = paste(sort(unique(fovs_per_well)), "FOVs per well")))
day_breaks <- unique(c(1, 7, 30, 100, 365, 1000, max(capacity$budget_days)))
day_breaks <- day_breaks[day_breaks <= max(capacity$budget_days)]

p10 <- ggplot(capacity, aes(budget_days, plates, colour = dimensions, shape = dimensions)) +
  geom_hline(data = max_plates, aes(yintercept = max_plates), linetype = "dashed", linewidth = 1) +
  geom_line(linewidth = 1.5) +
  geom_point(data = filter(capacity, budget_days %in% day_breaks), size = 7) +
  scale_x_log10(breaks = day_breaks) +
  scale_y_log10(labels = label_comma()) +
  facet_wrap(~fovs, nrow = 2, ncol = 2) +
  scale_colour_manual(values = palette) +
  scale_shape_manual(values = shapes) +
  labs(x = "scope time available (days)", y = paste0("plates profiled (", capacity$wells_per_plate[1], " wells)"), colour = "dimensions", shape = "dimensions") +
  guides(x = guide_axis(angle = 45)) +
  theme_bw(base_size = base_size)
ggsave("../figures/samples_profiled_per_dimension.png", p10, width = 16, height = 14, dpi = 200)
p10

width = 30
height = 30
options(repr.plot.width = width, repr.plot.height = height)
summary <- (p3 | wrap_elements(full = p8)) / (p10 | p9) +
  plot_annotation(tag_levels = "A") &
  theme(plot.tag = element_text(size = base_size + 6, face = "bold"))
ggsave("../figures/throughput_summary.png", summary, width = width, height = height, dpi = 600)


summary

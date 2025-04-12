#include <vector>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <random>
#include <ctime>
#include "MaskConfig.hpp"

/**
 * Human-like mouse movement generator. Ported from:
 * https://github.com/riflosnake/HumanCursor/blob/main/humancursor/utilities/human_curve_generator.py
 * Modified to use a more human-like easing function.
 */

class BezierCalculator {
 public:
  static long long factorial(int n) {
    if (n < 0) return -1;  // Indicate error
    long long result = 1;
    for (int i = 2; i <= n; i++) result *= i;
    return result;
  }

  static double binomial(int n, int k) {
    return static_cast<double>(factorial(n)) /
           (factorial(k) * factorial(n - k));
  }

  static double bernsteinPolynomialPoint(double x, int i, int n) {
    return binomial(n, i) * std::pow(x, i) * std::pow(1 - x, n - i);
  }

  static std::vector<double> bernsteinPolynomial(
      const std::vector<std::pair<double, double>>& points, double t) {
    int n = static_cast<int>(points.size()) - 1;
    double x = 0.0;
    double y = 0.0;
    for (int i = 0; i <= n; i++) {
      double bern = bernsteinPolynomialPoint(t, i, n);
      x += points[i].first * bern;
      y += points[i].second * bern;
    }
    return {x, y};
  }

  static std::vector<std::vector<double>> calculatePointsInCurve(
      int nPoints, const std::vector<std::pair<double, double>>& points) {
    std::vector<std::vector<double>> curvePoints;
    for (int i = 0; i < nPoints; i++) {
      double t = static_cast<double>(i) / (nPoints - 1);
      curvePoints.push_back(bernsteinPolynomial(points, t));
    }
    return curvePoints;
  }
};

class HumanizeMouseTrajectory {
 public:
  HumanizeMouseTrajectory(const std::pair<double, double>& fromPoint,
                          const std::pair<double, double>& toPoint)
      : fromPoint(fromPoint), toPoint(toPoint) {
    generateCurve();
  }

  std::vector<int> getPoints() const {
    std::vector<int> flatPoints;
    flatPoints.reserve(points.size() * 2);

    for (const auto& point : points) {
      flatPoints.push_back(static_cast<int>(std::round(point[0])));
      flatPoints.push_back(static_cast<int>(std::round(point[1])));
    }

    return flatPoints;
  }

 private:
  std::pair<double, double> fromPoint;
  std::pair<double, double> toPoint;
  std::vector<std::vector<double>> points;

  void generateCurve() {
    double leftBoundary = std::min(fromPoint.first, toPoint.first) - 80.0;
    double rightBoundary = std::max(fromPoint.first, toPoint.first) + 80.0;
    double downBoundary = std::min(fromPoint.second, toPoint.second) - 80.0;
    double upBoundary = std::max(fromPoint.second, toPoint.second) + 80.0;

    std::vector<std::pair<double, double>> internalKnots =
        generateInternalKnots(leftBoundary, rightBoundary, downBoundary,
                              upBoundary, 2);

    std::vector<std::vector<double>> curvePoints =
        generatePoints(internalKnots);
    curvePoints = distortPoints(curvePoints, 1.0, 1.0, 0.5);
    points = tweenPoints(curvePoints);
  }

  double easeOutQuad(double n) const {
    assert(n >= 0.0 && n <= 1.0 && "Argument must be between 0.0 and 1.0.");
    return -n * (n - 2);
  }

  std::vector<std::pair<double, double>> generateInternalKnots(
      double lBoundary, double rBoundary, double dBoundary, double uBoundary,
      int knotsCount) const {
    assert(isNumeric(lBoundary) && isNumeric(rBoundary) &&
           isNumeric(dBoundary) && isNumeric(uBoundary) &&
           "Boundaries must be numeric values");
    assert(knotsCount >= 0 && "knotsCount must be non-negative");
    assert(lBoundary <= rBoundary &&
           "Left boundary must be less than or equal to right boundary");
    assert(dBoundary <= uBoundary &&
           "Down boundary must be less than or equal to upper boundary");

    std::vector<double> knotsX =
        randomChoiceDoubles(lBoundary, rBoundary, knotsCount);
    std::vector<double> knotsY =
        randomChoiceDoubles(dBoundary, uBoundary, knotsCount);

    std::vector<std::pair<double, double>> knots;
    for (int i = 0; i < knotsCount; i++) {
      knots.emplace_back(knotsX[i], knotsY[i]);
    }
    return knots;
  }

  std::vector<double> randomChoiceDoubles(double min, double max,
                                          int size) const {
    std::vector<double> choices;
    std::uniform_real_distribution<double> dist(min, max);
    for (int i = 0; i < size; i++) {
      choices.push_back(dist(randomEngine));
    }
    return choices;
  }

  std::vector<std::vector<double>> generatePoints(
      const std::vector<std::pair<double, double>>& knots) const {
    assert(isListOfPoints(knots) && "Knots must be a valid list of points");
    int midPtsCnt = static_cast<int>(
        std::max({std::abs(fromPoint.first - toPoint.first),
                  std::abs(fromPoint.second - toPoint.second), 2.0}));
    std::vector<std::pair<double, double>> controlPoints = knots;
    controlPoints.insert(controlPoints.begin(), fromPoint);
    controlPoints.push_back(toPoint);
    return BezierCalculator::calculatePointsInCurve(midPtsCnt, controlPoints);
  }

  std::vector<std::vector<double>> distortPoints(
      const std::vector<std::vector<double>>& points, double distortionMean,
      double distortionStDev, double distortionFrequency) const {
    assert(isNumeric(distortionMean) && isNumeric(distortionStDev) &&
           isNumeric(distortionFrequency) && "Distortions must be numeric");
    assert(isListOfPoints(points) && "Points must be a valid list of points");
    assert(0.0 <= distortionFrequency && distortionFrequency <= 1.0 &&
           "distortion_frequency must be in range [0,1]");

    std::vector<std::vector<double>> distorted;
    distorted.push_back(points.front());

    std::normal_distribution<double> normalDist(distortionMean,
                                                distortionStDev);
    std::uniform_real_distribution<double> uniformDist(0.0, 1.0);

    for (size_t i = 1; i < points.size() - 1; i++) {
      double x = points[i][0];
      double y = points[i][1];
      double delta = 0.0;
      if (uniformDist(randomEngine) < distortionFrequency) {
        delta = std::round(normalDist(randomEngine));
      }
      distorted.push_back({x, y + delta});
    }
    distorted.push_back(points.back());
    return distorted;
  }

  int32_t getMaxTime() const {
    if (auto maxTime = MaskConfig::GetDouble("humanize:maxTime")) {
      return static_cast<int32_t>(maxTime.value() * 100);
    }
    return 150;
  }

  int32_t getMinTime() const {
    if (auto minTime = MaskConfig::GetDouble("humanize:minTime")) {
      return static_cast<int32_t>(minTime.value() * 100);
    }
    return 0;
  }

  std::vector<std::vector<double>> tweenPoints(
      const std::vector<std::vector<double>>& points) const {
    assert(isListOfPoints(points) && "List of points not valid");

    double totalLength = 0.0;
    for (size_t i = 1; i < points.size(); ++i) {
      double dx = points[i][0] - points[i - 1][0];
      double dy = points[i][1] - points[i - 1][1];
      totalLength += std::sqrt(dx * dx + dy * dy);
    }

    // Uses a power scale to keep the speed consistent
    int targetPoints = std::min(
        getMaxTime(),
        std::max(getMinTime() + 2, static_cast<int>(std::pow(totalLength, 0.25) * 20)));

    std::vector<std::vector<double>> res;
    for (int i = 0; i < targetPoints; i++) {
      double t = static_cast<double>(i) / (targetPoints - 1);
      double easedT = easeOutQuad(t);
      int index = static_cast<int>(easedT * (points.size() - 1));
      res.push_back(points[index]);
    }
    return res;
  }

  bool isNumeric(double val) const { return !std::isnan(val); }

  bool isListOfPoints(
      const std::vector<std::pair<double, double>>& points) const {
    for (const auto& p : points) {
      if (!isNumeric(p.first) || !isNumeric(p.second)) return false;
    }
    return true;
  }

  bool isListOfPoints(const std::vector<std::vector<double>>& points) const {
    for (const auto& p : points) {
      if (p.size() != 2 || !isNumeric(p[0]) || !isNumeric(p[1])) return false;
    }
    return true;
  }

  mutable std::default_random_engine randomEngine{std::random_device{}()};
};
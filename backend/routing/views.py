from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def health(request):
    return Response({'status': 'ok'})


@api_view(['POST'])
def routes(request):
    """Plan weather-aware routes.

    Expected body: {origin, destination, departure (ISO datetime), load_weight_lb}

    TODO (you build this):
      1. Validate input (consider a DRF Serializer in routing/serializers.py).
      2. Geocode origin/destination -> services.ors.geocode()
      3. Get up to 3 routes -> services.ors.get_routes()
      4. For each route: sample checkpoints + ETAs -> services.weather.sample_checkpoints()
         then fetch forecasts -> services.weather.get_forecast_at()
      5. Classify each checkpoint -> services.risk.classify_checkpoint()
      6. Pick best -> services.recommend.recommend()
      7. Return routes, checkpoints, risk summary, recommendation.
    """
    return Response({
        'placeholder': True,
        'received': request.data,
        'routes': [],
        'recommended_route_index': None,
    })

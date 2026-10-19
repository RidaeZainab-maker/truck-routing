from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=200000)
    interval_miles = serializers.ChoiceField(choices=[10, 25, 50], default=25)
